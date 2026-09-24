# 登录 / 会话 / 角色。
#
# 三条规矩，都是「不做会出事」的那种：
#
#   1. **不内置任何默认口令**。库里一个用户都没有时，第一个打开页面的人走「创建管理员」，
#      而不是拿 admin/admin 登录。内网工具也一样：默认口令 = 全网都知道的口令，
#      而且它一旦被写进文档就再也没人改。
#   2. 口令只存 pbkdf2 散列。`hashlib` 是标准库 —— 为这个装 passlib/bcrypt 不值得，
#      也会让无梯子环境的构建多一个失败点。
#   3. 会话存在**服务端**（SQLite）。签名 cookie 做不到「退出登录立刻失效」和
#      「改完口令把别处的登录踢掉」，而这两件事恰好是老师最在意的。
#
# 角色只有三个，且判定的是**动作**不是数据：能不能改东西、能不能管用户。
import hashlib
import hmac
import secrets

from flask import request, jsonify, g

COOKIE = 'asb_sid'          # 会话 cookie 名
TTL_DAYS = 7                # 空闲 7 天过期，每次带着有效会话访问就续期
ALGO = 'pbkdf2_sha256'
ITERATIONS = 200_000

ROLE_ZH = {'admin': '管理员', 'teacher': '老师', 'viewer': '只读'}
ROLES = tuple(ROLE_ZH)

# 能改数据的角色 / 能管用户的角色。写成元组是为了 require() 可读：
# @auth.require(*auth.CAN_WRITE)
CAN_WRITE = ('admin', 'teacher')
CAN_ADMIN = ('admin',)


# ---------------------------------------------------------------- 口令

def hash_password(password, iterations=ITERATIONS):
    """`pbkdf2_sha256$迭代次数$盐$散列`。迭代次数写进串里 —— 以后调大参数，
    老用户还能照旧登录（verify 用的是串里记的那个值）。"""
    if not password:
        raise ValueError('口令不能为空')
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return f'{ALGO}${iterations}${salt.hex()}${h.hex()}'


def verify_password(password, stored):
    """常数时间比对。格式坏了当验证失败，不抛异常 —— 登录接口不该因为一行脏数据 500。"""
    try:
        algo, iters, salt_hex, want = (stored or '').split('$')
        if algo != ALGO:
            return False
        got = hashlib.pbkdf2_hmac('sha256', (password or '').encode('utf-8'),
                                  bytes.fromhex(salt_hex), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), want)


def needs_rehash(stored):
    """散列用的参数已经落后于当前设置 → 登录成功后顺手升级一次。"""
    try:
        algo, iters, _, _ = (stored or '').split('$')
        return algo != ALGO or int(iters) < ITERATIONS
    except (ValueError, TypeError):
        return True


def new_token():
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------- 会话 / 角色

class AuthError(Exception):
    """带 HTTP 状态码的鉴权错误。"""

    def __init__(self, message, code=401):
        super().__init__(message)
        self.code = code


class Auth:
    def __init__(self, store, ttl_days=TTL_DAYS):
        self.store = store
        self.ttl_days = ttl_days

    # ---- 初始化状态
    def need_setup(self):
        """库里一个用户都没有 → 还没初始化过。"""
        return self.store.user_count() == 0

    # ---- 注册 / 登录 / 退出
    def setup(self, username, password, display=''):
        """创建第一个管理员。**只在没有任何用户时可用** —— 否则任何人都能靠这个接口
        给自己开一个管理员账号。"""
        if not self.need_setup():
            raise AuthError('已经初始化过了，请直接登录', 403)
        self._check_password(password)
        user = self.store.create_user(username, hash_password(password),
                                     role='admin', display=display)
        return user

    def login(self, username, password):
        u = self.store.user_by_name(username)
        if not u or not verify_password(password, u['pwd']):
            # 用户名不存在和口令错**回同一句话** —— 不然这个接口就是用户名枚举器。
            raise AuthError('用户名或口令不对')
        if needs_rehash(u['pwd']):
            self.store.set_password(u['id'], hash_password(password))
        self.store.touch_login(u['id'])
        token = new_token()
        self.store.create_session(token, u['id'], self.ttl_days)
        return self.store.user(u['id']), token

    def logout(self, token):
        if token:
            self.store.delete_session(token)

    def change_password(self, user, old, new):
        """本人改口令。改完把**所有**会话掐掉 —— 口令泄露的场景下，
        「改了口令但别处的登录还在」等于没改。"""
        u = self.store.user(user['id'])
        if not verify_password(old, u['pwd']):
            raise AuthError('原口令不对', 400)
        self._check_password(new)
        self.store.set_password(u['id'], hash_password(new))
        self.store.delete_user_sessions(u['id'])

    @staticmethod
    def _check_password(password):
        if not password or len(password) < 8:
            raise AuthError('口令至少 8 位', 400)

    # ---- 从请求里认人
    def current(self):
        token = request.cookies.get(COOKIE) or _bearer(request)
        sess = self.store.session(token)
        if not sess:
            return None
        u = self.store.user(sess['user_id'])
        if not u:
            self.store.delete_session(token)
            return None
        self.store.touch_session(token, self.ttl_days)
        g.session_token = token
        return u

    # ---- 装饰器
    def require(self, *roles):
        """@auth.require(*auth.CAN_WRITE)。返回 401 还是 403 分得很清：
        没登录 → 401（前端跳登录页）；登录了但角色不够 → 403（前端提示没权限）。"""
        def deco(fn):
            def wrapper(*a, **kw):
                u = getattr(g, 'user', None)
                if not u:
                    return jsonify({'error': '未登录', 'needLogin': True}), 401
                if roles and u['role'] not in roles:
                    return jsonify({'error': f'当前身份（{ROLE_ZH.get(u["role"], u["role"])}）'
                                             f'不能做这个操作'}), 403
                return fn(*a, **kw)
            wrapper.__name__ = getattr(fn, '__name__', 'wrapper')
            return wrapper
        return deco


def _bearer(req):
    """也认 `Authorization: Bearer <token>`。

    命令行测试脚本、curl 排查时带 cookie 很别扭，而会话表本来就只看 token 字符串 ——
    多认一个请求头不增加任何攻击面。
    """
    h = req.headers.get('Authorization', '')
    return h[7:].strip() if h.lower().startswith('bearer ') else None


def set_cookie(resp, token, secure=False):
    resp.set_cookie(COOKIE, token, max_age=TTL_DAYS * 86400, httponly=True,
                    samesite='Lax', secure=secure, path='/')
    return resp


def clear_cookie(resp):
    resp.set_cookie(COOKIE, '', max_age=0, httponly=True, samesite='Lax', path='/')
    return resp


def user_json(u):
    """给前端的用户信息（**不要**把 pwd 带出去）。"""
    if not u:
        return None
    return {'id': u['id'], 'username': u['username'], 'display': u['display'],
            'role': u['role'], 'roleZh': ROLE_ZH.get(u['role'], u['role'])}
