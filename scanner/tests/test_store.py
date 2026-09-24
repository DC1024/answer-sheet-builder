# 持久化层测试：schema / 类型往返 / 事务 / 级联 / 并发 / 会话。
#
#   python tests/test_store.py
#
# 这一层的价值全在「静默」两个字上：库里存错了类型、事务没回滚、外键没开，
# 界面看起来都正常 —— 直到某天判分全是 0，或者删了考试发现学生还在。
# 所以这里不测「能不能存」，测「存进去再读回来还是不是原来那个东西」。
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np                                  # noqa: E402

from app import store as S                          # noqa: E402
from app import stats as st                         # noqa: E402

FAILS = []


def ok(cond, label, extra=''):
    print(('  ✅ ' if cond else '  ❌ ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


def eq(got, want, label):
    ok(got == want, label, f'（期望 {want}，实测 {got}）')


def raises(fn, exc, label):
    try:
        fn()
    except exc as e:
        ok(True, label, str(e)[:70])
        return
    except Exception as e:                          # noqa: BLE001
        ok(False, label, f'抛的是 {type(e).__name__}: {e}')
        return
    ok(False, label, '没有抛异常')


TMP = tempfile.mkdtemp(prefix='asb-store-test-')
DB = os.path.join(TMP, 'test.db')
st_ = S.Store(DB)


def stu(sid, answers=None, name='', extra=None):
    d = {'sid': sid, 'name': name, 'cls': '高三(1)班', 'answers': answers or {},
         'pages': [{'ok': True, 'page': 0}], 'issues': [], 'baseIssues': [],
         'sidSource': 'sheet'}
    if extra:
        d.update(extra)
    return d


ANS = {1: {'answer': 'D', 'flag': 'ok', 'best': 0.827, 'ratios': {'A': 0.2, 'D': 1.0}},
       2: {'answer': 'C', 'flag': 'ok', 'best': 0.8, 'ratios': {'A': 0.1, 'C': 1.0}},
       3: {'answer': None, 'flag': 'blank', 'best': 0.0, 'ratios': {'A': 0.15}}}

print('=== A. 建库与版本 ===')
eq(st_.schema_version(), S.SCHEMA_VERSION, '新库直接是当前 schema 版本')
eq(st_.user_count(), 0, '新库没有用户（所以要引导创建管理员，而不是发个默认口令）')
st_.set_meta('probe', {'a': 1})
eq(st_.get_meta('probe'), {'a': 1}, 'meta 存得进读得出')
st_.close()
st_ = S.Store(DB)
eq(st_.get_meta('probe'), {'a': 1}, '重开同一个文件，数据还在（这就是「重启不丢」的本质）')

print('\n=== B. 题号键的类型往返（最该钉死的一条）===')
# 内存里 answers 的键是 **int**（题号来自模板）。JSON 只认字符串键 ——
# 漏了归一化的表现不是报错，是 stats 里 ans.get(1) 全部落空、全班 0 分。
print('     内存里题号键:', {type(k).__name__ for k in ANS})
eq({type(k).__name__ for k in ANS}, {'int'}, '前提：内存里的题号键是 int')
raw = S._dumps(S._fix_qkeys({'answers': ANS}, True))
eq(max(type(k).__name__ == 'str' for k in S._loads(raw)['answers']), True,
   '写进 JSON 后题号键变成字符串（JSON 的硬限制，不是 bug）')
back = S._fix_qkeys(S._loads(raw), False)['answers']
eq(sorted(back), [1, 2, 3], '读回来还原成 int')
eq(sorted({type(k).__name__ for k in back}), ['int'], '类型也对')
eq(back, ANS, '内容一字不差')

ex = st_.create_exam('类型往返', owner_id=None)
st_.save_students(ex['id'], [stu('2026010234', ANS, '张伟明')])
loaded = st_.students(ex['id'])[0]
eq(sorted({type(k).__name__ for k in loaded['answers']}), ['int'],
   '**经过 SQLite 一趟，学生 answers 的题号键仍是 int**')
eq(loaded['answers'], ANS, '学生 answers 内容无损')

# 最有力的断言：判分结果在存/取前后必须一致。漏了归一化时这里会是 0。
key = {1: 'D', 2: 'C'}
before = st.score(ANS, [1, 2, 3], key)
after = st.score(loaded['answers'], [1, 2, 3], key)
eq((before, after), (2, 2), '判分前后一致（漏掉键归一化的话这里是 0）')
wrong = st.summarize([{'name': 'x', 'answers': loaded['answers']}], [1, 2, 3], key)
eq(wrong['sheets'][0]['score'], 2, 'summarize 也算得到分（它用的是同一套键）')

st_.set_answer_key(ex['id'], {1: 'D', 10: 'B'})
eq(st_.exam(ex['id'])['answerKey'], {1: 'D', 10: 'B'}, '标准答案往返后键也是 int')

st_.add_scans(ex['id'], [('rid1', 'a.png', ANS, None, None, None, 'a.png')])
scan = st_.scans(ex['id'])[0]
eq(sorted({type(k).__name__ for k in scan['answers']}), ['int'], '单张扫描结果的键也是 int')
eq(scan['answers'], ANS, '单张扫描结果内容无损')

print('\n=== C. numpy 标量不能让落库炸掉 ===')
# omr 里只要有人少写一个 float()，落库就会在**整批识别跑完之后**抛异常 —— 那时候
# 结果已经算出来了，却因为存不进去而丢掉。_scalar 兜住这一层。
np_stu = stu('2026010235', {1: {'answer': 'A', 'flag': 'ok', 'best': np.float32(0.5),
                               'ratios': {'A': np.float64(0.9)}}})
st_.save_students(ex['id'], [np_stu])
got = st_.students(ex['id'])[0]['answers'][1]
eq((type(got['best']).__name__, got['best']), ('float', 0.5), 'np.float32 → python float')
eq(type(got['ratios']['A']).__name__, 'float', 'np.float64 → python float')
raises(lambda: S._dumps({'x': object()}), TypeError, '真存不了的类型要明确报错，不能静默丢字段')

print('\n=== D. 事务：存一半失败必须整体回滚 ===')
good = [stu('A1'), stu('A2')]
st_.save_students(ex['id'], good)
eq(len(st_.students(ex['id'])), 2, '先存进去 2 个')
raises(lambda: st_.save_students(ex['id'], good + [stu('A3', extra={'bad': object()})]),
       TypeError, '第三个学生写不进去 → 抛异常')
eq([s['sid'] for s in st_.students(ex['id'])], ['A1', 'A2'],
   '回滚成功：原来的 2 个还在，没有留下「删了一半」的考试')

print('\n=== E. 外键级联：删考试要连学生和扫描件一起走 ===')
ex2 = st_.create_exam('待删', owner_id=None)
st_.save_students(ex2['id'], [stu('B1')])
st_.add_scans(ex2['id'], [('rid2', 'b.png', ANS, None, None, None, 'b.png')])
eq((len(st_.students(ex2['id'])), len(st_.scans(ex2['id']))), (1, 1), '删之前学生和扫描件都在')
st_.delete_exam(ex2['id'])
eq(st_.exam(ex2['id']), None, '考试没了')
eq(st_.students(ex2['id']), [], '学生跟着走了（外键 ON DELETE CASCADE 真的开着）')
eq(st_.scans(ex2['id']), [], '扫描件也走了（不会留下孤儿行）')

print('\n=== F. 迁移守卫：库比代码旧又找不到迁移函数 → 必须报错 ===')
old_db = os.path.join(TMP, 'old.db')
tmp = S.Store(old_db)
tmp.set_meta('schema_version', 0)
tmp.close()
raises(lambda: S.Store(old_db), S.StoreError,
       '版本对不上就报错（静默用一个结构不对的库，坏的是老师的数据）')

print('\n=== G. 会话：过期、续期、吊销 ===')
u = st_.create_user('t1', 'hash', role='teacher')
u2 = st_.create_user('t2', 'hash', role='teacher')
st_.create_session('tok-a', u['id'], ttl_days=7)
ok(st_.session('tok-a') is not None, '会话取得回来')
st_.touch_session('tok-a', ttl_days=7)
ok(st_.session('tok-a')['expires_at'] > st_.session('tok-a')['seen_at'], '续期把过期时间推后了')
st_.create_session('tok-old', u['id'], ttl_days=7)
st_.conn.execute('UPDATE sessions SET expires_at=? WHERE token=?', ('2000-01-01T00:00:00+08:00', 'tok-old'))
eq(st_.session('tok-old'), None, '过期会话读不到')
eq(st_.conn.execute("SELECT COUNT(*) c FROM sessions WHERE token='tok-old'").fetchone()['c'], 0,
   '过期会话就地删掉，不留垃圾')
st_.create_session('tok-b', u2['id'], ttl_days=7)
st_.delete_user_sessions(u['id'])
eq((st_.session('tok-a'), st_.session('tok-b'))[0], None, '按人吊销：t1 的会话没了')
ok(st_.session('tok-b') is not None, '别人的会话不受影响')
st_.delete_user(u2['id'])
eq(st_.conn.execute('SELECT COUNT(*) c FROM sessions WHERE user_id=?', (u2['id'],)).fetchone()['c'],
   0, '删账号会级联清掉它的会话')

print('\n=== H. 账号守卫 ===')
eq(st_.admin_count(), 0, '现在没有管理员')
a1 = st_.create_user('a1', 'hash', role='admin')
a2 = st_.create_user('a2', 'hash', role='admin')
eq(st_.admin_count(), 2, '两个管理员')
eq(st_.set_role(a2['id'], 'viewer') is None, True, '还有别的管理员时，降级允许')
ok(st_.admin_count() == 1, '现在只剩一个管理员（路由那边真能给管理员降级）')
raises(lambda: st_.set_role(a1['id'], 'viewer'), S.StoreError, '最后一个管理员不能降级')
raises(lambda: st_.delete_user(a1['id']), S.StoreError, '最后一个管理员不能删')
a3 = st_.create_user('a3', 'hash', role='admin')
eq(st_.delete_user(a1['id']) is None, True, '有别的管理员了，就能删')
st_.create_user('dupme', 'hash')
raises(lambda: st_.create_user('dupme', 'hash'), S.StoreError, '用户名重复要报错')
eq(st_.admin_count(), 1, 'a3 是现在唯一的管理员')

print('\n=== I. 并发写：8 个线程同时存同一个考试 ===')
errs = []


def hammer(i):
    try:
        for r in range(6):
            st_.save_students(ex['id'], [stu(f'T{i}-{r}')])
            st_.add_scans(ex['id'], [(f'r{i}-{r}', 'x.png', ANS, None, None, None, 'x.png')])
            st_.students(ex['id'])
            st_.scans(ex['id'])
    except Exception as e:                           # noqa: BLE001
        errs.append(f'{type(e).__name__}: {e}')


ths = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
[t.start() for t in ths]
[t.join() for t in ths]
eq(errs, [], '多线程并发读写不报错（连接 + 进程内锁 + busy_timeout 够用）')
ok(len(st_.students(ex['id'])) > 0, '并发之后库还是可用的',
   f"{len(st_.students(ex['id']))} 个学生 / {len(st_.scans(ex['id']))} 条扫描")

print('\n=== J. 第二个连接 = 另一个进程看到的 ===')
st_.set_meta('current_exam', ex['id'])
peer = S.Store(DB)
eq(peer.get_meta('current_exam'), ex['id'], '另一个连接读得到刚写的元信息')
eq(len(peer.students(ex['id'])) > 0, True, '另一个连接读得到学生')
eq(peer.exam(ex['id'])['name'], '类型往返', '考试名也对得上')
peer.close()
st_.close()

print('\n=== K. 阅卷工作台：grading 随考生落库、不随重识别丢失 ===')
# section J 末尾把 st_ 关了（验证「换进程读同一库」），这里重新打开同一个文件继续测。
st_ = S.Store(DB)
# 老师改完分，刷新/重新套名单/重启都不能让复核结论消失 —— 这是工作台能不能用的底线。
gx = st_.create_exam('阅卷工作台', owner_id=None)
st_.save_students(gx['id'], [stu('2026010234', ANS, '张伟明')])
st_.set_student_grading(gx['id'], '2026010234',
                        {'overrides': {1: True, 3: False}, 'manualScore': 5,
                         'review': True, 'note': '存疑'})
got = st_.students(gx['id'])[0]
ov = {int(k): v for k, v in (got.get('grading', {}).get('overrides') or {}).items()}
eq(ov.get(1), True, 'grading.overrides 读回（题号键归一化为 int）')
eq(got['grading'].get('review'), True, 'grading.review 落库并读回')
eq(got['grading'].get('manualScore'), 5, 'grading.manualScore 落库并读回')
# 重新套名单 / 重新保存：grading 必须跟着学生一起活下来
survive = st_.students(gx['id'])
st_.save_students(gx['id'], survive)
back = st_.students(gx['id'])[0]
eq(back.get('grading', {}).get('review'), True,
   'save_students 重存之后 grading 仍在（重识别/重套名单不丢复核结论）')
# 二次覆盖：overrides 整体替换，不是和旧值合并
st_.set_student_grading(gx['id'], '2026010234',
                        {'overrides': {2: False}, 'manualScore': None, 'review': False, 'note': ''})
g2 = st_.students(gx['id'])[0]['grading']
ov2 = {int(k): v for k, v in (g2.get('overrides') or {}).items()}
eq(ov2.get(2), False, 'overrides 整体替换（旧覆盖被清）')
eq(g2.get('manualScore'), None, 'manualScore 清空生效')
eq(g2.get('review'), False, 'review 覆盖为 False')
raises(lambda: st_.set_student_grading(gx['id'], '不存在', {}), S.StoreError,
       '对不存在的考生存复核 → 报错而不是静默写空')

print('\n' + '=' * 56)
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f in FAILS:
        print('   -', f)
    sys.exit(1)
print('🎉 持久化层全部通过')
