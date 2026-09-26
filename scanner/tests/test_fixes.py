# 人工修正 + 方案误判率统计测试。
#
#   python tests/test_fixes.py
#
# 覆盖这次需求的两件事：
#   1. 老师能改掉机器读错的答案 —— 修正落库、进判分、进分布统计、导出后还在，
#      而且「机器原读」必须留着（误判率统计全靠它）。
#   2. 每道题标记「识别用的哪套方案」（rule / cnn / both），并按方案算「被老师
#      改掉的比例」—— 用来判断哪套方案误判更少。
#
# 关键陷阱（store._QKEYED 那条）也在这钉死：人工修正表是「题号当键」的字典，
# 落库过 JSON 键会变字符串，不还原就跟 int 键的 answers 对不上 → 修正静默失效。
import io
import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# 必须在 import server 之前设好库路径（数据库句柄在模块导入时打开）。
os.environ['ASB_DATA'] = tempfile.mkdtemp(prefix='asb-fix-test-')
os.environ['ASB_DB'] = os.path.join(os.environ['ASB_DATA'], 'test.db')

from app import server                          # noqa: E402
from app import fixes as F                      # noqa: E402
from tests import _fixtures                     # noqa: E402

FIX = _fixtures.FIX
FAILS = []


def ok(cond, label, extra=''):
    print(('  ✅ ' if cond else '  ❌ ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


def eq(got, want, label):
    ok(got == want, label, f'（期望 {want}，实测 {got}）')


def img(name):
    return open(os.path.join(FIX, name), 'rb').read()


def mkzip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


EXAM_ID = None            # 由 batch4() 铺班时记下当前考试 id，避免用 STORE 反查（依赖顺序太脆）


def batch4():
    """铺 4 位考生：目录名当考号（2026010234…237），内容用 s01…s04 素材。"""
    global EXAM_ID
    r = post_batch(mkzip([
        ('一个班/2026010234/正面.png', img('s01.png')),
        ('一个班/2026010235/正面.png', img('s02.png')),
        ('一个班/2026010236/正面.png', img('s03.png')),
        ('一个班/2026010237/正面.png', img('s04.png')),
    ]))
    j = r.get_json() or {}
    if (j.get('exam') or {}).get('id'):
        EXAM_ID = j['exam']['id']
    return r


c = server.app.test_client()
USER, PW = 'tester', 'testpass123'
c.post('/api/setup', json={'username': USER, 'password': PW})
c.post('/api/login', json={'username': USER, 'password': PW})
c.post('/api/template', data={'file': (io.BytesIO(img('template.json')), 'template.json')},
       content_type='multipart/form-data')


def post_batch(zip_bytes, name='一个班.zip', **form):
    data = {'files': (io.BytesIO(zip_bytes), name)}
    data.update(form)
    return c.post('/api/batch', data=data, content_type='multipart/form-data')


print('=== A. 纯函数：修正的规整与生效 ===')
# 'B' 字符串 与 {'answer':'B'} 两种写法都收
n = F.normalize_entry('b')
eq(n['answer'], 'B', '小写字母转大写')
ok(n.get('at') and n.get('by') is not None, '修正带时间与操作人字段')
n2 = F.normalize_entry({'answer': ' aB c ', 'note': ' 备注 '}, who='tester')
eq(n2['answer'], 'ABC', '去空白/只留字母')
eq(n2['note'], ' 备注 ', '备注保留')

# 非法输入
for bad in (None, '', '  ', '123', '1'):
    try:
        F.normalize_entry(bad)
        ok(False, f'非法答案 {bad!r} 该报错')
    except F.FixError:
        ok(True, f'非法答案 {bad!r} 报错')
# 'ABC123' 里数字被剥掉、只留字母 ABC —— 这是设计（多选如 AC 合法），不是报错
eq(F.normalize_entry('ABC123')['answer'], 'ABC', '混入数字剥掉后留字母（ABC 合法）')

# normalize_all：题号键统一成 int（_QKEYED 陷阱的第一环）
raw = F.normalize_all({'1': 'B', '3': {'answer': 'AC'}, '7': 'D'})
eq(sorted(raw), [1, 3, 7], '题号键归一化成 int')
eq(raw[3]['answer'], 'AC', '对象写法解析正确')
eq(F.normalize_all(None), {}, '空输入 → 空修正表')
eq(F.normalize_all(''), {}, '空字符串 → 空修正表')
try:
    F.normalize_all([1, 2])
    ok(False, '列表不是合法修正表')
except F.FixError:
    ok(True, '列表不是合法修正表 → 报错')

print('\n=== B. apply()：改答案、保机器原读、不覆盖、空改不算 ===')
answers = {1: {'answer': 'C', 'flag': 'ok', 'by': 'rule', 'best': 0.5},
           2: {'answer': 'B', 'flag': 'faint', 'by': 'rule'},
           3: {'answer': None, 'flag': 'blank', 'by': 'rule'}}
merged, changed = F.apply(answers, F.normalize_all({1: 'B', 3: 'A'}))
eq(merged[1]['answer'], 'B', '第 1 题答案被改成 B')
eq(merged[1]['machine'], 'C', '机器原读保留（误判率统计要靠它）')
eq(merged[1]['machineBy'], 'rule', '机器原读的方案也保留')
eq(merged[1]['flag'], 'fixed', '修正后 flag 标记为 fixed')
eq(merged[1]['by'], 'fix', '来源标成人工修正')
ok(merged[1].get('fixAt'), '修正带时间戳')
eq(sorted(changed), [1, 3], '发生变化的题号集合')
ok(merged[1].get('fixNote') is not None, '备注字段就位')
eq(merged[2], answers[2], '没改的题原样保留')
# 关键：apply 不修改入参
eq(answers[1]['answer'], 'C', '入参未被 apply 污染')

merged2, changed2 = F.apply(answers, F.normalize_all({1: 'C'}))   # 改成跟机器原读一样
eq(changed2, set(), '点了但答案没变 → 不算一次修正（否则误判率虚高）')
ok(merged2[1].get('machine') is None, '没实际改动 → 不标 machine（不记录虚假修正）')

print('\n=== C. engine_accuracy：按方案算「被老师改掉的比例」===')
# 人工构造：rule 定音 10 题、老师改 2；cnn 定音 6 题、老师改 1；both 3 题、没改
# （修正条目用归一化后的形状 —— 路由层 apply 之前会先过 normalize_all）
sheets = []
for i in range(1, 11):
    sheets.append({'answers': {i: {'answer': 'A', 'flag': 'ok', 'by': 'rule'}},
                   'fixes': ({i: F.normalize_entry('B')} if i <= 2 else {})})
for i in range(11, 17):
    sheets.append({'answers': {i: {'answer': 'C', 'flag': 'ok', 'by': 'cnn'}},
                   'fixes': ({i: F.normalize_entry('D')} if i == 11 else {})})
for i in range(17, 20):
    sheets.append({'answers': {i: {'answer': 'A', 'flag': 'ok', 'by': 'both'}}})
# 一条无来源（老数据）修正：分子照记 unknown，分母也必须有 unknown（修复过的坑）
sheets.append({'answers': {20: {'answer': 'A', 'flag': 'ok'}},
               'fixes': {20: F.normalize_entry('B')}})
acc = F.engine_accuracy(sheets, qnos=set(range(1, 21)))
byrow = {r['engine']: r for r in acc['rows']}
eq(acc['decided'], 20, '分母 = 所有定音过的题（含 unknown）')
eq(acc['corrected'], 4, '分子 = 老师改掉的题（1 个改回原值不算）')
eq(acc['rate'], 20.0, '总修正率 4/20 = 20%')
eq(byrow['rule']['decided'], 10, 'rule 分母 10')
eq(byrow['rule']['corrected'], 2, 'rule 被改 2 → 修正率 20%')
eq(byrow['rule']['rate'], 20.0, 'rule 修正率')
eq(byrow['cnn']['decided'], 6, 'cnn 分母 6')
eq(byrow['cnn']['corrected'], 1, 'cnn 被改 1')
eq(byrow['cnn']['rate'], round(100 / 6, 1), 'cnn 修正率 16.7%')
eq(byrow['both']['decided'], 3, 'both 分母 3')
eq(byrow['both']['corrected'], 0, 'both 没被改')
eq(byrow['both']['rate'], 0.0, 'both 修正率 0%')
eq(byrow['unknown']['decided'], 1, 'unknown 分母 1（分子分母一致，不再产出残缺行）')
eq(byrow['unknown']['corrected'], 1, 'unknown 被改 1')
ok(any(c['key'] == 'rule:A->B' for c in acc['confusions']), '混淆表记录「机器读成啥→改成啥」')
ok('只统计「老师亲手改过的题」' in acc['caveat'], 'caveat 在（界面必须原样展示）')
# 排序：改动多的方案靠前，unknown 沉底
order = [r['engine'] for r in acc['rows']]
ok(order[0] == 'rule', '改动最多的方案排最前', str(order))
ok(order[-1] == 'unknown', '无来源信息沉底（rule/cnn 才是老师要对比的）', str(order))

print('\n=== D. /api/fix：落库 + 穿透判分 / 分布统计 / 导出 ===')
# 先铺一个班（4 人）。s01 → 2026010234，第 1 题机器读 D。
r = batch4()
stus = (r.get_json() or {}).get('students') or []
eq(len(stus), 4, '铺 4 位考生')
stub = next((s for s in stus if s['sid'] == '2026010234'), {})
eq((stub.get('answers') or {}).get('1', {}).get('answer'), 'D', '第 1 题机器读 D（待修正）')

# 第 1 题机器读 D，改成 B → 判分、分布、导出都要跟着变
r = c.post('/api/fix', json={'sid': '2026010234', 'fixes': {'1': 'B', '3': 'A'}})
j = r.get_json() or {}
ok(r.status_code == 200 and j.get('ok'), '保存修正 200', str(j)[:120])
ans = {int(k): v for k, v in j.get('answers', {}).items()}
eq(ans[1]['answer'], 'B', '回吐的生效答案第 1 题 = B')
eq(ans[1]['machine'], 'D', '回吐里机器原读仍可读')
eq(ans[1]['flag'], 'fixed', '回吐的生效 flag 是 fixed')

# 判分穿透：给一个 1 题为 D 的标准答案，改前该题对、改后该题错
c.post('/api/answer-key', json={'key': '1D'})
gj = c.get('/api/gradebook').get_json() or {}
row = next((x for x in gj.get('students') or [] if x['sid'] == '2026010234'), {})
ok(row.get('answers', {}).get('1', {}).get('answer') == 'B', '工作台逐题答案已是修正后 B')
ok(row.get('answers', {}).get('1', {}).get('machine') == 'D', '工作台逐题带机器原读')
eq(row.get('answers', {}).get('1', {}).get('by'), 'fix', '工作台逐题来源 = 人工修正')
eq(row.get('fixedQnos'), [1, 3], '工作台标记出被人工修正的题号')

# 分布统计：修正后 234 的第 1 题由 D→B；其余三位仍是 B/C/A（s03 本来就是 B）。
# → B 出现 2 次（s03 + 修正后的 234），D 不再出现。
stj = c.post('/api/stats', json={'key': '1D'}).get_json() or {}
q1 = next((q for q in stj.get('questions') or [] if q.get('no') == 1), {})
eq(q1.get('dist', {}).get('B'), 2, '分布统计里 B 计数 = 2（s03 本为 B + 修正后的 234）')
ok('D' not in (q1.get('dist') or {}), '分布统计里 D 已不存在（没人选 D 了）', str(q1.get('dist')))
eq(q1.get('dist', {}).get('A'), 1, '分布统计里 A 计数 = 1（s04 为 A）')

# 导出：答案列里第 1 题是 B（修正穿透到导出）
r = c.post('/api/export.csv', data={'key': '1D'})
lines = [l for l in r.data.decode('utf-8-sig').strip().splitlines() if l.strip()]
hdr = lines[0].split(',')
i1 = hdr.index('1')
zhang = next((l for l in lines if '2026010234' in l), '')
eq(zhang.split(',')[i1], 'B', '导出答案列第 1 题 = B（修正穿透到导出）')

print('\n=== E. _QKEYED 往返：落库读回键不丢（修正不能静默失效）===')
# 关键回归：fixes 是「题号当键」的字典，落库走 JSON 键变字符串。store 在内存里
# 还原成 int（让 apply() 匹配得上）；但**到了浏览器永远是字符串**（JSON 键只能是
# 字符串）——所以这里分两层断言：底层 store 保 int，线上 JSON 保内容不保类型。
stu = server.STORE.students(EXAM_ID, ['2026010234'])[0]
fx = stu.get('fixes') or {}
eq(sorted({type(k).__name__ for k in fx}), ['int'], 'store 层 fixes 键还原成 int')
eq(sorted(fx), [1, 3], 'store 层人工修正表题号键仍为 int')
# 线上 JSON：键必为字符串，但 apply() 已成功合并（gradebook 显示 B 即证明）——
# 若键归一化失败，修正会静默失效、这里会显示机器原读 D。
r = c.get('/api/students')
stus = r.get_json() or {}
stuw = next((s for s in stus.get('students') or [] if s['sid'] == '2026010234'), {})
eq(sorted(stuw.get('fixes') or {}), ['1', '3'], '线上 JSON 键为字符串（JSON 硬限制）')
eq((stuw.get('answers') or {}).get('1', {}).get('answer'), 'B', '线上生效答案仍是 B（修正没丢）')

print('\n=== F. 重传扫描件：人工修正不丢（save_students keep_manual）===')
# 重新上传同一批扫描 → 识别结果重新算，但修正必须按考号搬回来
r = batch4()
# batch 响应里的 students 是「刚识别完」的原始结果，不带 fixes（fixes 只在读取时
# 合并进视图）—— 要看修正是否还在，得走 /api/students 这个合并后的视图。
gj = c.get('/api/students').get_json() or {}
stus = gj.get('students') or []
stu = next((s for s in stus if s['sid'] == '2026010234'), {})
fx = stu.get('fixes') or {}
eq(sorted(map(int, fx)), [1, 3], '重传后修正仍在（keep_manual 搬回来了）')
# 工作台重新读：修正后答案还是 B
gj = c.get('/api/gradebook').get_json() or {}
row = next((x for x in gj.get('students') or [] if x['sid'] == '2026010234'), {})
eq(row.get('answers', {}).get('1', {}).get('answer'), 'B', '重传后第 1 题仍是修正后的 B')

print('\n=== G. 方案标识：批量接口 / 单张 / health ===')
# 批量接口带 engine 汇总（这份纯选择题 → 全 rule）
r = post_batch(mkzip([('一个班/2026010234/正面.png', img('s01.png')),
                      ('一个班/2026010235/正面.png', img('s02.png'))]))
j = r.get_json() or {}
eq((j.get('engine') or {}).get('engine'), 'rule', '选择题卷 → 整卷口径 rule')
eq((j.get('engine') or {}).get('byCount', {}).get('rule'), 40, '40 题全 rule（2 人 × 20）')
stus = j.get('students') or []
eq((stus[0].get('answers') or {}).get('1', {}).get('by'), 'rule', '逐题带方案来源')
# 单张扫描：同样带 engine 与逐题 by
r = c.post('/api/scan', data={'files': (io.BytesIO(img('s01.png')), 's01.png')},
           content_type='multipart/form-data')
j = r.get_json() or {}
res = (j.get('results') or [])[0]
eq((res.get('engine') or {}).get('engine'), 'rule', '单张结果也带 engine')
eq((res.get('questions') or [])[0].get('by'), 'rule', '单张逐题带 by')
# health：报告本服务当前生效方案（选择题恒为结构规则）
h = c.get('/api/health').get_json() or {}
eq((h.get('engine') or {}).get('choice'), 'rule', 'health 说明选择题方案 = rule')
ok((h.get('engine') or {}).get('choiceZh'), 'health 带方案中文名')

print('\n=== H. /api/fix/sid：改卷面考号 ===')
# 铺齐 5 位考生（目录名当考号）。注意批量是「整批替换」—— 只传 1 人会把其余
# 4 人冲掉，所以这里直接传满 5 人，保证下面改号时目标号 234 还在库里。
r = post_batch(mkzip([
    ('一个班/2026010234/正面.png', img('s01.png')),
    ('一个班/2026010235/正面.png', img('s02.png')),
    ('一个班/2026010236/正面.png', img('s03.png')),
    ('一个班/2026010237/正面.png', img('s04.png')),
    ('一个班/2026010238/正面.png', img('s05.png')),
]))
stus = (r.get_json() or {}).get('students') or []
eq(any(s['sid'] == '2026010238' for s in stus), True, '铺第 5 位考生 2026010238')
r = c.post('/api/fix/sid', json={'sid': '2026010238', 'newSid': '2026010288'})
ok(r.status_code == 200 and (r.get_json() or {}).get('ok'), '改考号 200', str(r.get_json())[:120])
eq((r.get_json() or {}).get('sid'), '2026010288', '新考号生效')
r = c.post('/api/fix/sid', json={'sid': '2026010288', 'newSid': '2026010238'})
ok(r.status_code == 200, '改回原考号')
# 重复考号拒绝（234 也在这批里，目标号存在）
r = c.post('/api/fix/sid', json={'sid': '2026010238', 'newSid': '2026010234'})
ok(r.status_code in (400, 404) and '已经有一份卷子' in (r.get_json() or {}).get('error', ''),
   '新考号已存在 → 拒绝并说明', str(r.get_json())[:120])

print('\n=== I. 权限：只读账号不能改答案 / 不能改考号 ===')
r = c.post('/api/users', json={'username': 'vviewer', 'password': 'vv12345', 'role': 'viewer'})
ok(r.status_code == 200, '新建只读账号', str(r.get_json())[:120])
cv = server.app.test_client()
cv.post('/api/login', json={'username': 'vviewer', 'password': 'vv12345'})
eq(cv.post('/api/fix', json={'sid': '2026010234', 'fixes': {'1': 'B'}}).status_code, 403,
   '只读账号改答案 → 403')
eq(cv.post('/api/fix/sid', json={'sid': '2026010234', 'newSid': '2026010238'}).status_code, 403,
   '只读账号改考号 → 403')
eq(cv.get('/api/engine-accuracy').status_code, 200, '只读账号能看误判率统计')

print('\n=== J. /api/engine-accuracy 服务端口径 ===')
# 当前生效集是 H 铺的 5 人整批。把 234 的第 1、3 题再钉一次修正（重传可能已搬回，
# 这里确保生效集里确实有修正），然后查服务端口径的误判率。
c.post('/api/fix', json={'sid': '2026010234', 'fixes': {'1': 'B', '3': 'A'}})
j = c.get('/api/engine-accuracy').get_json() or {}
byrow = {r['engine']: r for r in j.get('rows') or []}
# 分母 = 当前生效集里所有定音过的题（5 人 x 20 题，纯选择题 → 全 rule）
ok(j.get('decided') and j.get('decided') > 0, '服务端误判率分母 > 0（当前生效集的题数）',
   f"decided={j.get('decided')}")
eq(byrow.get('rule', {}).get('engine'), 'rule', 'rule 行在场')
# 234 的第 1、3 题被改掉 → 计入 rule 的 corrected
ok(j.get('corrected') is not None, '服务端误判率分子存在', f"corrected={j.get('corrected')}")
# corrected 至少包含 234 那两处修正（rule 桶里 corrected ≥ 2）
ok((byrow.get('rule', {}) or {}).get('corrected', 0) >= 2,
   'rule 桶的 corrected ≥ 2（234 的修正被统计）',
   f"rule.corrected={byrow.get('rule', {}).get('corrected')}")
ok(j.get('caveat'), '服务端回吐 caveat（界面要原样展示）')
# 混淆表至少有一条 rule:机器读→改后
ok(any('rule:' in (c['key'] or '') for c in j.get('confusions') or []), '混淆表含 rule 桶的记录')

print('\n' + '=' * 56)
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f in FAILS:
        print('   -', f)
    sys.exit(1)
print('🎉 人工修正与方案误判率统计全部通过')