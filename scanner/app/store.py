# 持久化层：把「这一个班的结果」从进程内存搬到 SQLite。
#
# 为什么必须落盘：批量识别一个班要几十秒到几分钟，识别完的东西原来只活在内存里 ——
# 容器一重建（改一行代码就得重建）、waitress 被重启，整批结果连同刚录进去的补录姓名
# 一起没了。老师得重扫一遍。
#
# 为什么是 SQLite 而不是写 JSON 文件：
#   - 一个班 50 人 × 2 面，写 JSON 每次都要整文件重写；两个人同时上传就互相覆盖。
#   - 需要「删掉一个考试、它的学生和扫描件跟着走」这种一致性 → 外键 + 事务。
#   - 单文件、无独立服务进程、标准库自带 sqlite3 —— **不新增任何依赖**。
#
# ⚠️ 这个文件里最容易出事的不是 SQL，是 **类型**。见 _dump_answers / _load_answers。
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta

SCHEMA_VERSION = 3

# 表结构 v1。全部 JSON 大字段（template / roster / answers / data）都按「哑存储」处理：
# 识别器以后多几个字段不用改表结构 —— 这也是把整个学生字典塞进 data 一列的原因。
DDL_V1 = """
CREATE TABLE meta (
  k TEXT PRIMARY KEY,
  v TEXT
);

CREATE TABLE users (
  id        INTEGER PRIMARY KEY,
  username  TEXT NOT NULL UNIQUE,
  display   TEXT NOT NULL DEFAULT '',
  role      TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'viewer')),
  pwd       TEXT NOT NULL,              -- 口令散列由 auth.py 算好传进来，store 不碰明文
  created_at TEXT NOT NULL,
  last_login TEXT
);

CREATE TABLE sessions (
  token      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  seen_at    TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE TABLE exams (
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL,
  owner_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  template     TEXT,                    -- 完整模板 JSON（识别要用）
  tpl_summary  TEXT,                    -- 界面摘要 JSON
  answer_key   TEXT,                    -- 标准答案 JSON
  roster       TEXT,
  roster_cols  TEXT,
  roster_source TEXT,
  overrides    TEXT,                    -- 人工补录 {sid: {name, cls}}，必须跟着考试一起活下来
  active_kind  TEXT,                    -- 'batch' | 'scan' | NULL
  active_ids   TEXT,                    -- JSON 数组
  rules        TEXT                     -- 自动评分规则 {题号: rule}（v2）
);

-- 批量结果：一个学生一行。
-- sid / name / cls / seq 提出来做列是为了排序和列表；其余整个学生字典进 data。
CREATE TABLE exam_students (
  exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
  sid     TEXT NOT NULL,
  seq     INTEGER NOT NULL DEFAULT 0,
  name    TEXT,
  cls     TEXT,
  data    TEXT NOT NULL,
  PRIMARY KEY (exam_id, sid)
);

-- 单张扫描的结果（「先扫几张试试」那条路）。批量会整批替换它。
CREATE TABLE exam_scans (
  exam_id  INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
  rid      TEXT NOT NULL,
  seq      INTEGER NOT NULL DEFAULT 0,
  name     TEXT NOT NULL,
  answers  TEXT NOT NULL,
  sid      TEXT,
  stu      TEXT,
  cls      TEXT,
  source   TEXT,
  PRIMARY KEY (exam_id, rid)
);
"""

# 以后加字段用：[(2, _migrate_to_v2)]，_migrate_to_v2(conn) 里写 ALTER/CREATE。
# 注意**只许加法**：老库里的数据是老师的东西，宁可留着一列没用，也不要 DROP。
def _migrate_to_v2(conn):
    """v2：加 exams.rules —— 自动评分规则。老库升级，缺列才补。"""
    cols = [r['name'] for r in conn.execute('PRAGMA table_info(exams)').fetchall()]
    if 'rules' not in cols:
        conn.execute('ALTER TABLE exams ADD COLUMN rules TEXT')


def _migrate_to_v3(conn):
    """v3：加 exam_scans.fixes —— 单张扫描的人工修正表。

    批量那条件走 exam_students.data（整条 JSON 落库，加字段不用改表），
    但单张扫描是**一列一字段**的表，新字段必须显式 ALTER。
    不加列的话写入会直接报 "no such column" —— 那是好事（响亮地失败）；
    真正的危险是有人为了绕开报错把 fixes 塞进别的列，那才会静默串味。
    """
    cols = [r['name'] for r in conn.execute('PRAGMA table_info(exam_scans)').fetchall()]
    if 'fixes' not in cols:
        conn.execute('ALTER TABLE exam_scans ADD COLUMN fixes TEXT')


MIGRATIONS = [(2, _migrate_to_v2), (3, _migrate_to_v3)]


class StoreError(Exception):
    """持久化层的错误，信息直接给用户看。"""


# ------------------------------------------------------------------ 类型闸门

def qno(key):
    """题号键归一化成 int。

    整条链路（模板的 `q['no']`、answers 的键、标准答案的键、stats 的 qnos）都按 int 走。
    这个函数是唯一的入口，落库和读回都过它 —— 保证 **存进去什么类型、读回来还是什么类型**。
    """
    if isinstance(key, bool):
        return key
    if isinstance(key, int):
        return key
    try:
        return int(str(key).strip())
    except (TypeError, ValueError, AttributeError):
        return key


def _scalar(v):
    """把不认识的对象降成 JSON 能写的东西。

    `np.float64` 恰好是 `float` 的子类所以能过，`np.float32 / np.int64` 过不去。
    加这层是因为：omr 里只要有人少写一个 `float()`，落库就会在**识别跑完之后**炸 ——
    那时候整批结果已经算出来了，却因为存不进去而丢掉，不值得。
    """
    if hasattr(v, 'item') and callable(v.item):        # numpy 标量
        return v.item()
    raise TypeError(f'这个类型写不进 JSON：{type(v).__name__}')


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=_scalar, allow_nan=False)


def _loads(raw, default=None):
    if raw is None or raw == '':
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


# --------------------------------------------------------------- 「题号当键」的字典
#
# 落盘最容易踩、也最安静的一个坑就在这里。
#
# 内存里题号是 **int**（模板的 q['no']、answers 的键、标准答案的键、stats 的 qnos 全是它），
# 但 JSON 的键**只能是字符串** —— 存一遍读回来就变成 `{"1": ...}`。
# 不还原的后果不是报错，是 `stats.summarize()/score()` 里的 `ans.get(1)` 全部落空：
# 成绩表上每个人 0 分、每个选项 0 人，**一声不吭**。
#
# 这个坑真的踩到了：`exam_scans` 用了 _dump_answers，而 `exam_students` 是把整个学生
# 字典丢进一列 JSON 的，当时漏了它里面的 answers —— 批量识别一切正常、界面也好看，
# 只有判分全 0。所以现在只有**一条**转换路径（下面三个函数），谁都不许自己手写。

def _qmap_out(m):
    """题号作键的字典 → JSON 串（键转字符串）。"""
    if not m:
        return None
    return _dumps({str(qno(k)): v for k, v in m.items()})


def _qmap_in(raw):
    """JSON 串 → 题号作键的字典（**键还原成 int**）。"""
    return {qno(k): v for k, v in (_loads(raw, {}) or {}).items()}


# 学生字典里「键是题号」的字段名。加新的同类型字段必须往这里加。
#
# fixes 必须在这里 —— 人工修正表也是「题号作键」。漏了它的后果正是上面警告的那种：
# 存进去 {"1": "B"}、读回来键还是字符串，而内存里答案是 int 键 → apply() 一题都匹配不上，
# **修正全部静默失效**（界面看着改了、刷新就回原样，且没有任何报错）。
_QKEYED = ('answers', 'fixes')


def _fix_qkeys(d, dump):
    """把一个字典里所有「题号作键」的字段统一键类型（dump=True 转 str，False 转 int）。"""
    if not isinstance(d, dict):
        return d
    out = dict(d)
    for f in _QKEYED:
        v = out.get(f)
        if isinstance(v, dict):
            out[f] = ({str(qno(k)): x for k, x in v.items()} if dump
                      else {qno(k): x for k, x in v.items()})
    return out


_dump_answers, _load_answers = _qmap_out, _qmap_in      # 单张扫描结果
_dump_key, _load_key = _qmap_out, _qmap_in              # 标准答案


def now():
    """带时区的 ISO 时间串（本地时间，人在库里看也读得懂）。"""
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _expires(days):
    return (datetime.now().astimezone() + timedelta(days=days)).isoformat(timespec='seconds')


# ------------------------------------------------------------------ Store

class Store:
    """一个进程共用一个连接 + 一把锁。

    waitress 是多线程的（server.py 里只有 8 个线程），一个请求一条 SQL 的量级 ——
    加锁比给每个线程开连接的复杂度划算得多，也好排查。
    """

    def __init__(self, path):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        # isolation_level=None → 自动提交模式，事务由我们自己 BEGIN/COMMIT 显式管。
        # python sqlite3 的历史默认值会「偷偷」在 DML 前开事务，跟显式 BEGIN 混用容易
        # 撞上 "cannot start a transaction within a transaction"。
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')      # 读写不互相阻塞
        self.conn.execute('PRAGMA foreign_keys=ON')       # 默认是关的，删考试要靠它级联
        self.conn.execute('PRAGMA busy_timeout=5000')
        try:
            self._migrate()
        except Exception:
            self.conn.close()      # 迁移失败别把连接留着（否则报错时文件还被占着）
            raise

    def close(self):
        with self._lock:
            self.conn.close()

    def _exec(self, sql, args=()):
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def _all(self, sql, args=()):
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def _one(self, sql, args=()):
        with self._lock:
            return self.conn.execute(sql, args).fetchone()

    def _migrate(self):
        """建表 / 升级。幂等：每次启动都会跑，已经是最新版本就什么都不做。"""
        with self._lock:
            has_meta = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
            if not has_meta:
                self.conn.executescript(DDL_V1)
                self.conn.execute('INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)',
                                  ('schema_version', str(SCHEMA_VERSION)))
                return
            row = self.conn.execute('SELECT v FROM meta WHERE k=?', ('schema_version',)).fetchone()
            # 注意别写成 `int(_loads(row['v'], 1) or 1)` —— `0 or 1` 是 1，
            # 会把「版本 0」这种最老的库当成最新版，守卫就白写了。
            ver = int(_loads(row['v'], 1)) if row else 1
            if ver < 1:
                # 版本 0 不是合法起点 —— 发布过的最早 schema 就是 v1。
                # 声称自己比 v1 还旧的库只能是结构损坏，不许迁移「修复」，必须报错。
                raise StoreError(
                    f'数据库结构版本是 {ver}，低于最早支持的版本 1 —— 库已损坏，'
                    f'拒绝打开（静默用一个结构不对的库，坏的是老师的数据）')
            for target, fn in MIGRATIONS:
                if ver < target:
                    fn(self.conn)
                    ver = target
            if ver != SCHEMA_VERSION:
                # 库比代码旧，却没有对应的迁移函数 —— 说明有人改了 SCHEMA_VERSION 忘记写迁移。
                # 这时**必须报错**：静默用一个结构对不上的库，坏的是老师的数据。
                raise StoreError(
                    f'数据库结构版本是 {ver}，本程序需要 {SCHEMA_VERSION}，'
                    f'但找不到从 {ver} 升级的迁移函数（检查 store.MIGRATIONS）')
            self.conn.execute('INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)',
                              ('schema_version', str(ver)))

    # ---------------------------------------------------------- 元信息
    def get_meta(self, k, default=None):
        row = self._one('SELECT v FROM meta WHERE k=?', (k,))
        return _loads(row['v'], default) if row else default

    def set_meta(self, k, v):
        self._exec('INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)', (k, _dumps(v)))

    def schema_version(self):
        return int(self.get_meta('schema_version', SCHEMA_VERSION) or SCHEMA_VERSION)

    # ---------------------------------------------------------- 用户
    #
    # 口令散列由 auth.py 算好传进来 —— store 完全不碰明文，也就没有「日志里漏出口令」的机会。

    def user_count(self):
        return self._one('SELECT COUNT(*) c FROM users')['c']

    def create_user(self, username, pwd_hash, role='teacher', display=''):
        username = (username or '').strip()
        if not username:
            raise StoreError('用户名不能为空')
        if role not in ('admin', 'teacher', 'viewer'):
            raise StoreError(f'不认识的角色：{role}')
        try:
            cur = self._exec('INSERT INTO users(username, display, role, pwd, created_at) '
                             'VALUES (?,?,?,?,?)', (username, display or username, role,
                                                    pwd_hash, now()))
        except sqlite3.IntegrityError:
            raise StoreError(f'用户名「{username}」已经存在')
        return self.user(cur.lastrowid)

    def user(self, uid):
        row = self._one('SELECT * FROM users WHERE id=?', (uid,))
        return dict(row) if row else None

    def user_by_name(self, username):
        row = self._one('SELECT * FROM users WHERE username=? COLLATE NOCASE', ((username or '').strip(),))
        return dict(row) if row else None

    def list_users(self):
        return [dict(r) for r in self._all(
            'SELECT id, username, display, role, created_at, last_login FROM users ORDER BY id')]

    def touch_login(self, uid):
        self._exec('UPDATE users SET last_login=? WHERE id=?', (now(), uid))

    def set_password(self, uid, pwd_hash):
        self._exec('UPDATE users SET pwd=? WHERE id=?', (pwd_hash, uid))

    def admin_count(self):
        return self._one("SELECT COUNT(*) c FROM users WHERE role='admin'")['c']

    def set_role(self, uid, role):
        if role not in ('admin', 'teacher', 'viewer'):
            raise StoreError(f'不认识的角色：{role}')
        u = self.user(uid)
        if not u:
            raise StoreError('没有这个账号')
        # 最后一个管理员不能降级 —— 和「不能删最后一个管理员」是同一件事的两面。
        # 漏了这条，管理员点一下「改成只读」就把自己锁在账号管理外面了（真的能点）。
        if u['role'] == 'admin' and role != 'admin' and self.admin_count() <= 1:
            raise StoreError('这是最后一个管理员，改成别的角色就没人能管账号了')
        self._exec('UPDATE users SET role=? WHERE id=?', (role, uid))

    def delete_user(self, uid):
        """删用户。最后一个 admin 不许删 —— 删完就没人能进管理页了。"""
        u = self.user(uid)
        if not u:
            return
        if u['role'] == 'admin' and self.admin_count() <= 1:
            raise StoreError('这是最后一个管理员，删了就没人能管理用户了')
        self._exec('DELETE FROM users WHERE id=?', (uid,))

    # ---------------------------------------------------------- 会话
    def create_session(self, token, user_id, ttl_days=7):
        self._exec('INSERT INTO sessions(token, user_id, created_at, seen_at, expires_at) '
                   'VALUES (?,?,?,?,?)', (token, user_id, now(), now(), _expires(ttl_days)))

    def session(self, token):
        """取会话。过期就地删掉 —— 不留「已过期但还在表里」的垃圾。"""
        if not token:
            return None
        row = self._one('SELECT * FROM sessions WHERE token=?', (token,))
        if not row:
            return None
        if row['expires_at'] <= now():
            self._exec('DELETE FROM sessions WHERE token=?', (token,))
            return None
        return dict(row)

    def touch_session(self, token, ttl_days=7):
        """每次带着有效会话访问就续期 —— 老师连着上一节课不该被踢出去。"""
        self._exec('UPDATE sessions SET seen_at=?, expires_at=? WHERE token=?',
                   (now(), _expires(ttl_days), token))

    def delete_session(self, token):
        self._exec('DELETE FROM sessions WHERE token=?', (token,))

    def delete_user_sessions(self, user_id):
        """改口令 / 停用账号时把这个人所有会话掐掉。"""
        self._exec('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def purge_sessions(self):
        return self._exec('DELETE FROM sessions WHERE expires_at <= ?', (now(),)).rowcount

    # ---------------------------------------------------------- 考试
    def create_exam(self, name, owner_id=None):
        name = (name or '').strip() or '未命名考试'
        cur = self._exec('INSERT INTO exams(name, owner_id, created_at, updated_at) '
                         'VALUES (?,?,?,?)', (name, owner_id, now(), now()))
        return self.exam(cur.lastrowid)

    def exams(self, owner_id=None, all_owners=False):
        # 列表里带上人数：界面的考试选择器要显示「N 人」，否则老师得逐个点进去看
        cols = ('e.*, (SELECT COUNT(*) FROM exam_students s WHERE s.exam_id = e.id) '
                'AS studentCount')
        if all_owners or owner_id is None:
            rows = self._all(f'SELECT {cols} FROM exams e ORDER BY e.updated_at DESC, e.id DESC')
        else:
            rows = self._all(f'SELECT {cols} FROM exams e WHERE e.owner_id=? '
                             f'ORDER BY e.updated_at DESC, e.id DESC', (owner_id,))
        out = []
        for r in rows:
            d = dict(r)
            d.pop('template', None)          # 列表里不带完整模板（可能几十 KB）
            d.pop('answer_key', None)
            d.pop('roster', None)
            d.pop('overrides', None)
            d['hasTemplate'] = bool(r['template'])
            d['answerKeyCount'] = len(_load_key(r['answer_key']))
            out.append(d)
        return out

    def exam(self, exam_id):
        row = self._one('SELECT * FROM exams WHERE id=?', (exam_id,))
        if not row:
            return None
        d = dict(row)
        d['templateJson'] = _loads(d.pop('template'), None)
        d['tplSummary'] = _loads(d.pop('tpl_summary'), None)
        d['answerKey'] = _load_key(d.pop('answer_key'))
        d['rules'] = _loads(d.pop('rules'), {}) or {}
        d['roster'] = _loads(d.pop('roster'), {}) or {}
        d['rosterCols'] = _loads(d.pop('roster_cols'), {}) or {}
        d['overrides'] = _loads(d.pop('overrides'), {}) or {}
        d['activeIds'] = _loads(d.pop('active_ids'), []) or []
        return d

    def touch_exam(self, exam_id):
        self._exec('UPDATE exams SET updated_at=? WHERE id=?', (now(), exam_id))

    def rename_exam(self, exam_id, name):
        self._exec('UPDATE exams SET name=?, updated_at=? WHERE id=?',
                   ((name or '').strip() or '未命名考试', now(), exam_id))

    def delete_exam(self, exam_id):
        """删考试。学生和扫描件靠外键级联一起走 —— 不然会留下孤儿行。"""
        self._exec('DELETE FROM exams WHERE id=?', (exam_id,))

    def set_template(self, exam_id, template, summary):
        self._exec('UPDATE exams SET template=?, tpl_summary=?, updated_at=? WHERE id=?',
                   (_dumps(template), _dumps(summary), now(), exam_id))

    def set_roster(self, exam_id, roster, cols, source):
        self._exec('UPDATE exams SET roster=?, roster_cols=?, roster_source=?, updated_at=? '
                   'WHERE id=?', (_dumps(roster), _dumps(cols), source, now(), exam_id))

    def set_answer_key(self, exam_id, key):
        self._exec('UPDATE exams SET answer_key=?, updated_at=? WHERE id=?',
                   (_dump_key(key), now(), exam_id))

    def set_rules(self, exam_id, rules):
        self._exec('UPDATE exams SET rules=?, updated_at=? WHERE id=?',
                   (_dumps(rules or {}), now(), exam_id))

    def get_rules(self, exam_id):
        row = self._one('SELECT rules FROM exams WHERE id=?', (exam_id,))
        return _loads(row['rules'], {}) or {} if row else {}

    def set_overrides(self, exam_id, overrides):
        self._exec('UPDATE exams SET overrides=?, updated_at=? WHERE id=?',
                   (_dumps(overrides or {}), now(), exam_id))

    def set_active(self, exam_id, kind, ids):
        self._exec('UPDATE exams SET active_kind=?, active_ids=?, updated_at=? WHERE id=?',
                   (kind, _dumps(list(ids or [])), now(), exam_id))

    # ---------------------------------------------------------- 学生（批量结果）
    def save_students(self, exam_id, students, keep_manual=False):
        """整批替换。一个事务里做完 —— 中途失败不会留下「删了一半」的考试。

        keep_manual=True 时，先把库里已有的 `grading`（人工复核）与 `fixes`（人工修正）
        按考号搬回到新数据上。**批量重传必须开这个** —— 否则老师重新上传一次扫描件，
        之前逐题改的答案和复核标记会被整批替换静默清空：界面刷新一下才发现在，
        而且没有任何提示。识别结果是新算的，但人工劳动不是。

        注意只有 sid 对得上的才搬得过去。考号本身被改过、或这次识别换了考号，
        就对不上了 —— 这时**宁可丢掉也不要猜**（猜错等于把甲的修正记到乙头上）。
        """
        carry = {}
        if keep_manual:
            for row in self._all('SELECT sid, data FROM exam_students WHERE exam_id=?',
                                 (exam_id,)):
                d = _fix_qkeys(_loads(row['data'], {}) or {}, False)
                keep = {k: d[k] for k in ('grading', 'fixes') if d.get(k)}
                if keep:
                    carry[str(row['sid'])] = keep
        with self._lock:
            try:
                self.conn.execute('BEGIN')
                self.conn.execute('DELETE FROM exam_students WHERE exam_id=?', (exam_id,))
                for i, s in enumerate(students):
                    rec = _fix_qkeys(s, True)
                    for k, v in (carry.get(str(s.get('sid'))) or {}).items():
                        rec.setdefault(k, v)
                    self.conn.execute(
                        'INSERT INTO exam_students(exam_id, sid, seq, name, cls, data) '
                        'VALUES (?,?,?,?,?,?)',
                        (exam_id, str(s.get('sid')), i, s.get('name') or '',
                         s.get('cls') or '', _dumps(rec)))
                self.conn.execute('UPDATE exams SET updated_at=? WHERE id=?', (now(), exam_id))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def students(self, exam_id, sids=None):
        if sids is None:
            rows = self._all('SELECT data FROM exam_students WHERE exam_id=? ORDER BY seq, sid',
                             (exam_id,))
        else:
            sids = [str(s) for s in sids]
            if not sids:
                return []
            marks = ','.join('?' * len(sids))
            rows = self._all(f'SELECT data FROM exam_students WHERE exam_id=? '
                             f'AND sid IN ({marks}) ORDER BY seq, sid', (exam_id, *sids))
        return [_fix_qkeys(_loads(r['data'], {}) or {}, False) for r in rows]

    def set_student_grading(self, exam_id, sid, grading):
        """把人工复核结果写进某个考生的 data.grading。

        不碰其余字段 —— 识别出来的答案、补录的姓名都原样保留。grading 是整个学生字典
        里的一个普通键，store 用 `_fix_qkeys` 整条落库、整条读回，所以它会跟着
        `save_students` / 重新套名单一起活下来（跟 answers 同一条往返路径，不另搞一套）。
        """
        row = self._one('SELECT data FROM exam_students WHERE exam_id=? AND sid=?',
                        (exam_id, str(sid)))
        if not row:
            raise StoreError('没有这个考生：' + str(sid))
        d = _fix_qkeys(_loads(row['data'], {}) or {}, False)
        d['grading'] = grading
        with self._lock:
            try:
                self.conn.execute('BEGIN')
                self.conn.execute(
                    'UPDATE exam_students SET data=? WHERE exam_id=? AND sid=?',
                    (_dumps(_fix_qkeys(d, True)), exam_id, str(sid)))
                self.conn.execute('UPDATE exams SET updated_at=? WHERE id=?', (now(), exam_id))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return d

    def set_student_fixes(self, exam_id, sid, fixes):
        """写某个考生的人工修正表（改机器读错的答案）。

        和 set_student_grading 并列但**语义不同**：grading 改「判分结论」，
        这里改「答案本身」。两者都只动自己那个键，互不干扰。
        """
        row = self._one('SELECT data FROM exam_students WHERE exam_id=? AND sid=?',
                        (exam_id, str(sid)))
        if not row:
            raise StoreError('没有这个考生：' + str(sid))
        d = _fix_qkeys(_loads(row['data'], {}) or {}, False)
        d['fixes'] = fixes or {}
        with self._lock:
            try:
                self.conn.execute('BEGIN')
                self.conn.execute(
                    'UPDATE exam_students SET data=? WHERE exam_id=? AND sid=?',
                    (_dumps(_fix_qkeys(d, True)), exam_id, str(sid)))
                self.conn.execute('UPDATE exams SET updated_at=? WHERE id=?', (now(), exam_id))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return d

    def set_student_sid(self, exam_id, old_sid, new_sid):
        """改某个考生的考号（卷面考号读错时用）。

        主键是 (exam_id, sid)，改考号等于搬一行 —— 不能直接 UPDATE，得先读出来再
        用新 sid 写回、删掉旧行。新 sid 已经存在时**拒绝**（否则会把两个人合并成一个，
        而且丢了谁都不知道）。
        """
        old_sid, new_sid = str(old_sid), str(new_sid)
        if not new_sid.strip():
            raise StoreError('新考号不能为空')
        if old_sid == new_sid:
            return
        row = self._one('SELECT data FROM exam_students WHERE exam_id=? AND sid=?',
                        (exam_id, old_sid))
        if not row:
            raise StoreError('没有这个考生：' + old_sid)
        dup = self._one('SELECT sid FROM exam_students WHERE exam_id=? AND sid=?',
                        (exam_id, new_sid))
        if dup:
            raise StoreError(f'考号 {new_sid} 已经有一份卷子了 —— 请先处理那份，'
                             f'不然两个人的答案会混在一起')
        d = _fix_qkeys(_loads(row['data'], {}) or {}, False)
        d['sid'] = new_sid
        with self._lock:
            try:
                self.conn.execute('BEGIN')
                self.conn.execute('UPDATE exam_students SET sid=?, data=? '
                                  'WHERE exam_id=? AND sid=?',
                                  (new_sid, _dumps(_fix_qkeys(d, True)), exam_id, old_sid))
                self.conn.execute('UPDATE exams SET updated_at=? WHERE id=?', (now(), exam_id))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    # ---------------------------------------------------------- 单张扫描结果
    def add_scans(self, exam_id, items):
        """items: [(rid, name, answers, sid, stu, cls, source)]"""
        with self._lock:
            try:
                self.conn.execute('BEGIN')
                base = self._one('SELECT COALESCE(MAX(seq), -1) m FROM exam_scans '
                                 'WHERE exam_id=?', (exam_id,))['m'] + 1
                for i, (rid, name, answers, sid, stu_name, cls, source) in enumerate(items):
                    self.conn.execute(
                        'INSERT OR REPLACE INTO exam_scans'
                        '(exam_id, rid, seq, name, answers, sid, stu, cls, source) '
                        'VALUES (?,?,?,?,?,?,?,?,?)',
                        (exam_id, rid, base + i, name, _dump_answers(answers), sid,
                         stu_name, cls, source))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def clear_scans(self, exam_id):
        self._exec('DELETE FROM exam_scans WHERE exam_id=?', (exam_id,))

    def scans(self, exam_id, rids=None):
        if rids is None:
            rows = self._all('SELECT * FROM exam_scans WHERE exam_id=? ORDER BY seq, rid',
                             (exam_id,))
        else:
            rids = [str(r) for r in rids]
            if not rids:
                return []
            marks = ','.join('?' * len(rids))
            rows = self._all(f'SELECT * FROM exam_scans WHERE exam_id=? AND rid IN ({marks}) '
                             f'ORDER BY seq, rid', (exam_id, *rids))
        out = []
        for r in rows:
            keys = r.keys()
            out.append({'id': r['rid'], 'name': r['name'],
                        'answers': _load_answers(r['answers']),
                        # 老库（v2）没有这一列 —— 用 keys() 判一下而不是硬取，
                        # 免得升级过程中读到半新半旧的库时炸掉整页。
                        'fixes': _load_answers(r['fixes']) if 'fixes' in keys else {},
                        'sid': r['sid'], 'stu': r['stu'], 'cls': r['cls'],
                        'source': r['source']})
        return out

    def set_scan_fixes(self, exam_id, rid, fixes):
        """写单张扫描的人工修正。只动 fixes 一列，识别出来的 answers 原样保留。"""
        row = self._one('SELECT rid FROM exam_scans WHERE exam_id=? AND rid=?',
                        (exam_id, str(rid)))
        if not row:
            raise StoreError('没有这张扫描件：' + str(rid))
        self._exec('UPDATE exam_scans SET fixes=? WHERE exam_id=? AND rid=?',
                   (_dump_answers(fixes), exam_id, str(rid)))

    def set_scan_sid(self, exam_id, rid, sid):
        """改单张扫描的卷面考号（机器读错考号时用）。"""
        row = self._one('SELECT rid FROM exam_scans WHERE exam_id=? AND rid=?',
                        (exam_id, str(rid)))
        if not row:
            raise StoreError('没有这张扫描件：' + str(rid))
        self._exec('UPDATE exam_scans SET sid=? WHERE exam_id=? AND rid=?',
                   (str(sid), exam_id, str(rid)))
