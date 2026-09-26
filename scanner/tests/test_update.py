# 更新检测 + 设置接口测试（纯离线，不碰网络）。
#
#   python tests/test_update.py
#
# 覆盖三件事：
#   1. 版本号比较（`v1.0.3` / `1.0.4-rc.1` / 乱七八糟的 tag）
#   2. `update.check()` 在**成功 / 404 / 断网**三种情况下的返回结构 ——
#      重点断言「失败不抛异常」，因为学校内网连不上 GitHub 是常态
#   3. `/api/settings`、`/api/update` 两个接口：鉴权、落盘、缓存、失败不缓存
import importlib
import json
import os
import sys
import tempfile
from urllib.error import HTTPError, URLError

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# **必须在 import server 之前**把数据目录指到临时位置：server 在模块导入时就
# 建库、建 settings.json，别写到服务真正在用的 data/ 里。
TMP = tempfile.mkdtemp(prefix='asb-upd-test-')
os.environ['ASB_DATA'] = TMP
os.environ['ASB_DB'] = os.path.join(TMP, 'test.db')

from app import update as upd                   # noqa: E402
from app import server                          # noqa: E402
from app import settings as settings_mod        # noqa: E402

FAILS = []


def ok(cond, label, extra=''):
    print(('  ✅ ' if cond else '  ❌ ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


def eq(got, want, label):
    ok(got == want, label, f'（期望 {want}，实测 {got}）')


# ---------------------------------------------------------------- 1. 版本号

print('【1】版本号比较')
for text, want in [('v1.0.3', (1, 0, 3)), ('1.0.3', (1, 0, 3)), ('V2.1', (2, 1, 0)),
                   ('1.0.3+build.7', (1, 0, 3)), ('1.0.4-rc.1', (1, 0, 4)),
                   ('', (0, 0, 0)), ('nope', (0, 0, 0)), ('v1.10.2', (1, 10, 2))]:
    eq(upd.parse_version(text), want, f'parse_version({text!r})')

ok(upd.is_newer('v1.0.4', '1.0.3'), '1.0.4 > 1.0.3 → 有新版本')
ok(not upd.is_newer('v1.0.3', '1.0.3'), '同版本 → 不算新')
ok(not upd.is_newer('v1.0.2', '1.0.3'), '旧版本 → 不算新')
ok(upd.is_newer('v1.1.0', '1.0.99'), '1.1.0 > 1.0.99（按段比，不是按字符串）')
ok(upd.is_newer('v2.0.0', 'v1.10.2'), '2.0.0 > 1.10.2')
ok(not upd.is_newer('', '1.0.3'), '空 tag → 不误报有新版本')
ok(not upd.is_newer('garbage', '1.0.3'), '乱七八糟的 tag → 不误报')


# ---------------------------------------------------------------- 2. check()

print('\n【2】update.check() 的三种结局')


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Stub:
    """把 update 模块里的 `urlopen` 换成假的，避免真去打 GitHub。

    注意要替的是**模块里那个名字**（`update.py` 是 `from urllib.request import
    urlopen`，所以 `upd.urlopen` 就是它的全局）—— 如果代码写的是
    `urllib.request.urlopen(...)`，替 `upd.urllib` 是无效的。
    """

    def __init__(self, fn):
        self.urlopen = fn


def with_stub(fn):
    saved = upd.urlopen
    upd.urlopen = fn
    try:
        return upd.check('1.0.3')
    finally:
        upd.urlopen = saved


rel = {'tag_name': 'v1.0.4', 'name': 'v1.0.4', 'body': '### 新增\n- 某某',
       'html_url': 'https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.4',
       'published_at': '2026-10-01T00:00:00Z'}
r = with_stub(lambda req, timeout=None: _Resp(rel))
eq(r['ok'], True, '查得到 → ok=True')
eq(r['latest'], 'v1.0.4', 'latest 取到 tag')
eq(r['hasUpdate'], True, '比当前新 → hasUpdate=True')
eq(r['notes'], '### 新增\n- 某某', '发行说明带回来了')
ok(r['url'].endswith('v1.0.4'), '带上发行版页面地址')

r = with_stub(lambda req, timeout=None: _Resp(dict(rel, tag_name='v1.0.3')))
eq(r['hasUpdate'], False, '最新就是当前版本 → hasUpdate=False')


def _raise_404(req, timeout=None):
    raise HTTPError('u', 404, 'Not Found', {}, None)


r = with_stub(_raise_404)
eq(r['ok'], False, '404 → ok=False')
ok('还没有发布过' in r['error'], '404 给出人话解释', r['error'])


def _raise_net(req, timeout=None):
    raise URLError('no route to host')


r = with_stub(_raise_net)
eq(r['ok'], False, '断网 → ok=False（**不抛异常**）')
ok('连不上 GitHub' in r['error'], '断网给出人话解释', r['error'])

r = with_stub(lambda req, timeout=None: _Resp(['不是字典']))
eq(r['ok'], False, '返回体不是对象 → ok=False 而不是崩')

# 请求头里必须带 User-Agent（GitHub 不带就 403）
seen = {}


def _capture(req, timeout=None):
    seen['ua'] = (req.headers or {}).get('User-agent') or (req.headers or {}).get('User-Agent')
    return _Resp(rel)


with_stub(_capture)
ok(bool(seen.get('ua')), '请求带上了 User-Agent（GitHub 不带会 403）', str(seen.get('ua')))


# ---------------------------------------------------------------- 3. Settings 落盘

print('\n【3】settings.json 落盘')
st = settings_mod.Settings(os.path.join(TMP, 'probe-settings.json'))
eq(st.get()['auto_check_update'], True, '默认开启自动检查更新')
st.patch({'auto_check_update': False})
st2 = settings_mod.Settings(os.path.join(TMP, 'probe-settings.json'))
eq(st2.get()['auto_check_update'], False, '关掉后重新读文件 → 关着的（真的落盘了）')
st2.patch({'auto_check_update': True, 'evil_key': 'x', '__version__': '9.9.9'})
eq('evil_key' in st2.get(), False, '白名单之外的字键一律丢弃')
eq(st2.get()['auto_check_update'], True, '合法键照常生效')
with open(os.path.join(TMP, 'broken.json'), 'w', encoding='utf-8') as fh:
    fh.write('{ 这不是 json')
eq(settings_mod.Settings(os.path.join(TMP, 'broken.json')).get()['auto_check_update'], True,
   '配置文件损坏 → 退回默认值，不抛异常')


# ---------------------------------------------------------------- 4. 接口

print('\n【4】/api/settings 与 /api/update')
c = server.app.test_client()

eq(c.get('/api/settings').status_code, 401, '未登录读设置 → 401')
eq(c.get('/api/update').status_code, 401, '未登录查更新 → 401')

USER, PW = 'admin', 'admintest1234'
eq(c.post('/api/setup', json={'username': USER, 'password': PW}).status_code, 200, '初始化管理员')
eq(c.post('/api/login', json={'username': USER, 'password': PW}).status_code, 200, '登录成功')

r = c.get('/api/settings')
j = r.get_json() or {}
eq(r.status_code, 200, '登录后能读设置')
eq(j.get('version'), server.APP_VERSION, '带上当前版本号')
eq(j.get('settings', {}).get('auto_check_update'), True, '默认自动检查更新开着')
ok(j.get('checkInterval'), '带上缓存间隔（前端用来解释为什么没重复查）')

r = c.post('/api/settings', json={'auto_check_update': False})
eq(r.status_code, 200, '关掉自动检查 → 200')
eq((r.get_json() or {}).get('ok'), True, '返回 ok')
eq(((r.get_json() or {}).get('settings') or {}).get('auto_check_update'), False,
   '关掉后返回的就是关着的')
eq(server.SETTINGS.get()['auto_check_update'], False, '服务端内存里的设置也变了')
with open(os.path.join(TMP, 'settings.json'), encoding='utf-8') as fh:
    eq(json.load(fh)['auto_check_update'], False, 'settings.json 真的落盘了')

eq(c.post('/api/settings', json={'auto_check_update': True}).status_code, 200, '再打开')

# 只读账号不能改设置，但能看
r = c.post('/api/users', json={'username': 'vv', 'password': 'viewpass1234', 'role': 'viewer'})
eq(r.status_code, 200, '建一个只读账号')
c2 = server.app.test_client()
eq(c2.post('/api/login', json={'username': 'vv', 'password': 'viewpass1234'}).status_code, 200,
   '只读账号登录')
eq(c2.get('/api/settings').status_code, 200, '只读账号能看设置')
eq(c2.post('/api/settings', json={'auto_check_update': False}).status_code, 403,
   '只读账号改设置 → 403')

# ---- /api/update：成功 → 缓存；失败 → 不缓存

calls = {'n': 0}
saved_check = server.upd.check


def fake_ok(current, *a, **kw):
    calls['n'] += 1
    return {'ok': True, 'current': current, 'latest': 'v9.9.9', 'hasUpdate': True,
            'url': 'https://example.invalid/r', 'name': 'v9.9.9', 'notes': 'n',
            'publishedAt': '', 'publishedUrl': '', 'error': ''}


server.upd.check = fake_ok
try:
    j = c.get('/api/update').get_json() or {}
    eq(j.get('hasUpdate'), True, '查更新 → 有新版本')
    eq(j.get('cached'), False, '第一次是实查')
    eq(calls['n'], 1, '确实查了一次 GitHub')
    j2 = c.get('/api/update').get_json() or {}
    eq(j2.get('cached'), True, '6 小时内再查 → 走缓存')
    eq(calls['n'], 1, '没有重复打 GitHub')
    ok(j2.get('checkedAt'), '缓存结果带上上次检查时间')
    c.get('/api/update?force=1')
    eq(calls['n'], 2, 'force=1 → 强制重查')

    before = server.SETTINGS.get()['last_check']
    def fake_fail(current, *a, **kw):
        calls['n'] += 1
        return dict(upd._blank(current, error='连不上 GitHub（URLError）—— 内网/离线环境属正常'))

    server.upd.check = fake_fail
    j = c.get('/api/update?force=1').get_json() or {}
    eq(j.get('ok'), False, '查不到 → ok=False')
    ok('连不上 GitHub' in (j.get('error') or ''), '失败原因直接给人话', str(j.get('error')))
    eq(server.SETTINGS.get()['last_check'], before, '**失败不写缓存**（否则会被锁在「查不到」里 6 小时）')
finally:
    server.upd.check = saved_check

print('\n' + '=' * 56)
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f in FAILS:
        print('   -', f)
    sys.exit(1)
print('🎉 更新检测与设置接口测试全部通过')
