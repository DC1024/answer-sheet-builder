# 主观题（人工阅卷）端到端测试：模板解析 → 作答区裁剪落盘 → 打分落库 → 成绩单/导出。
#
#   python tests/test_subjective.py
#
# 为什么必须有这一层：「主观题」横跨制卡端导出的模板、扫描端裁剪、成绩单、CSV 四段，
# 每段单测都可能过、拼起来却对不上（典型：模板里 region 有了、但路由取不到文件；
# 或者打的分落了库、总分却没把它算进去）。这里就盯「拼起来对不对」。
#
# 素材：tests/fixtures/template.json（20 道选择题）就地改造成「20 选择 + 2 主观」，
# 不新增二进制夹具 —— 裁剪出来的作答区本来就不需要是「真题」，
# 需要验的是坐标换算、落盘、路由、算分这一整条链路。
import io
import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# **必须在 import server 之前**设好库路径（句柄是模块导入时打开的）
os.environ['ASB_DB'] = os.path.join(tempfile.mkdtemp(prefix='asb-subj-test-'), 'test.db')

import cv2                                                              # noqa: E402
import numpy as np                                                      # noqa: E402

from app import server                                                  # noqa: E402

FIX = os.path.join(HERE, 'fixtures')
FAILS = []


def ok(cond, label, extra=''):
    print(('  \u2705 ' if cond else '  \u274c ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


def eq(got, want, label, extra=''):
    ok(got == want, label, extra or f'（期望 {want!r}，实测 {got!r}）')


def img(name):
    return open(os.path.join(FIX, name), 'rb').read()


def mkzip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def crop_size(region, px_per_mm=8.0, pad_mm=1.5):
    """region_crop 会裁成多大（像素）。

    边界是闭区间（`+1`），所以 2×rx 之后还要加 1 —— 测试里重复一遍这个算术，
    是为了在有人改 region_crop 的取样口径时这里会立刻红，而不是悄悄变了一点尺寸。
    """
    rx = max(1.0, region['w'] * px_per_mm / 2.0) + pad_mm * px_per_mm
    ry = max(1.0, region['h'] * px_per_mm / 2.0) + pad_mm * px_per_mm
    return int(round(rx * 2)) + 1, int(round(ry * 2)) + 1


# ---------------------------------------------------------------- 造一个带主观题的模板

# 第 21 题：按小问给分（(1) 4 分 + (2) 6 分）
# 第 22 题：整题给分（6 分）
SUB_REGION_A = {'x': 107.5, 'y': 111.0, 'w': 185.0, 'h': 8.0}    # 盖住第一行填涂圈 → 一定有墨迹
SUB_REGION_B = {'x': 105.0, 'y': 200.0, 'w': 180.0, 'h': 30.0}   # 空白区（够大，好核对尺寸）


def subjective_template():
    t = json.loads(img('template.json').decode('utf-8'))
    t['questionCount'] = 22
    t['pages'][0]['questions'] += [
        {'no': 21, 'x': SUB_REGION_A['x'], 'y': SUB_REGION_A['y'], 'region': SUB_REGION_A,
         'points': 10.0, 'subs': [{'label': '(1)', 'points': 4.0},
                                  {'label': '(2)', 'points': 6.0}]},
        {'no': 22, 'x': SUB_REGION_B['x'], 'y': SUB_REGION_B['y'], 'region': SUB_REGION_B,
         'points': 6.0},
    ]
    return json.dumps(t, ensure_ascii=False).encode('utf-8')


def bubble_template():
    return json.dumps(json.loads(img('template.json').decode('utf-8')),
                      ensure_ascii=False).encode('utf-8')


ROSTER = ('考号,姓名,班级\n'
          '2026010234,张伟明,高三(12)班\n'
          '2026010235,李思,高三(12)班\n')

c = server.app.test_client()
USER, PW = 'subjadmin', 'testpass123'


def login():
    return c.post('/api/login', json={'username': USER, 'password': PW})


def upload_tpl(data):
    return c.post('/api/template', data={'file': (io.BytesIO(data), 'template.json')},
                  content_type='multipart/form-data')


def gradebook():
    return c.get('/api/gradebook').get_json() or {}


def row_of(gj, sid):
    return next(x for x in gj.get('students') or [] if x['sid'] == sid)


print('=== A. 模板解析：主观题被认出来（而不是当成「没标准答案的空题」）===')
eq(c.post('/api/setup', json={'username': USER, 'password': PW}).status_code, 200, '初始化管理员')
eq(login().status_code, 200, '登录')
r = upload_tpl(subjective_template())
ok(r.status_code == 200, '上传模板 200', f'HTTP {r.status_code} {str(r.get_json())[:140]}')
summary = (r.get_json() or {}).get('summary') or {}
subj = summary.get('subjective') or {}
eq(sorted(subj.keys(), key=int), ['21', '22'], '模板摘要里有两道主观题')
eq(subj['21']['points'], 10.0, '第 21 题满分 = 小问之和 4+6')
eq([s['points'] for s in subj['21']['subs']], [4.0, 6.0], '第 21 题带 2 个小问')
eq(subj['22']['points'], 6.0, '第 22 题满分 6')
eq(subj['22']['subs'], [], '第 22 题没有小问 → 整题给分模式')
eq(subj['21']['page'], 0, '记下主观题在哪一面（前端据此找裁剪图）')
eq(summary.get('questionCount'), 22, '题号全集含主观题')

print('\n=== B. 单张扫描：作答区裁剪落盘 + 路由可取 ===')
r = c.post('/api/scan', data={'files': (io.BytesIO(img('s01.png')), 's01.png'), 'page': '0'},
           content_type='multipart/form-data')
j = r.get_json() or {}
ok(r.status_code == 200, '单张扫描 200', f'HTTP {r.status_code} {str(j)[:140]}')
res = (j.get('results') or [{}])[0]
rid = res.get('id')
eq(sorted(res.get('regions') or [], key=int), ['21', '22'], '两道主观题的作答区都裁出来了',
   str(res.get('regions')))
ok(bool(rid), '结果带扫描 id')

# 用 s01 的实际答案当标准答案 —— 这样后面的「客观分」是个确定的数（满分 20），
# 而不是靠猜夹具内容（猜错了测试会以「0 分也通过」的方式静默失去意义）。
KEYMAP = {q['no']: q['answer'] for q in res['questions']
          if q['no'] <= 20 and q.get('answer')}
KEY = ' '.join(f'{k}{v}' for k, v in sorted(KEYMAP.items()))
OBJ_MAX = len(KEYMAP)
ok(OBJ_MAX >= 15, 's01 至少读出 15 道客观题（太少说明夹具/识别退化了）', f'读了 {OBJ_MAX} 道')
ok(all(not str(v).isdigit() for v in KEYMAP.values()), '标准答案只由字母组成（不含主观题的分）',
   str(sorted(KEYMAP.items()))[:80])

r = c.get(f'/api/region/{rid}/21.jpg')
eq(r.status_code, 200, '裁剪图接口 200')
ok(r.headers.get('Content-Type', '').startswith('image/jpeg'), 'Content-Type 是 JPEG',
   str(r.headers.get('Content-Type')))
crop = cv2.imdecode(np.frombuffer(r.data, np.uint8), cv2.IMREAD_COLOR)
ok(crop is not None, '裁剪图能解码成图片')
ew, eh = crop_size(SUB_REGION_A)
eq(crop.shape[1], ew, '裁剪宽度 = (region 宽 + 2×1.5mm 余量) × 8px/mm')
eq(crop.shape[0], eh, '裁剪高度 = (region 高 + 2×1.5mm 余量) × 8px/mm')
ok(crop.shape[0] < 400, '裁的是作答区，不是整页（整页高 2376px）', f'实测高 {crop.shape[0]}px')
ok(float(crop.mean()) < 250, '裁剪区里有内容（不是一整片纯白）', f'均值 {crop.mean():.1f}')

r = c.get(f'/api/region/{rid}/22.jpg')
crop_b = (cv2.imdecode(np.frombuffer(r.data, np.uint8), cv2.IMREAD_COLOR)
          if r.status_code == 200 else None)
ok(crop_b is not None and crop_b.shape[0] == crop_size(SUB_REGION_B)[1],
   '第 22 题裁剪图也存在且尺寸对得上',
   f'HTTP {r.status_code}, shape {None if crop_b is None else crop_b.shape}'
   f', 期望高 {crop_size(SUB_REGION_B)[1]}')

eq(c.get(f'/api/region/{rid}/99.jpg').status_code, 404, '没裁过的题号 → 404（不猜不编）')
eq(c.get(f'/api/region/{rid}.jpg').status_code, 404, '路径拼错 → 404（不是 500）')

print('\n=== C. 批量上传：主观题区域随页落库 ===')
zip_main = mkzip([
    ('一个班/2026010234/正面.png', img('s01.png')),
    ('一个班/2026010235/正面.png', img('s02.png')),
    ('一个班/名单.csv', ROSTER.encode('utf-8')),
])
r = c.post('/api/batch', data={'files': (io.BytesIO(zip_main), '一个班.zip')},
           content_type='multipart/form-data')
j = r.get_json() or {}
ok(r.status_code == 200, '批量接口 200', f'HTTP {r.status_code} {str(j)[:140]}')
eq(len(j.get('students') or []), 2, '归组出 2 位考生')
p0 = ((j.get('students') or [{}])[0].get('pages') or [{}])[0]
eq(sorted(p0.get('regions') or [], key=int), ['21', '22'], '页记录里带着已裁剪的主观题号')
page_rid = p0.get('id')
ok(page_rid and c.get(f'/api/region/{page_rid}/21.jpg').status_code == 200,
   '批量路径裁出来的图同样能通过路由取到（两条入口写的是同一个文件名规则）')

r = c.post('/api/answer-key', json={'key': KEY})
eq(r.status_code, 200, '保存标准答案')
eq((r.get_json() or {}).get('count'), OBJ_MAX,
   '只存了客观题的标准答案（主观题本来就没有标准答案）')

print('\n=== D. 成绩单：客观分 / 主观分 / 满分 ===')
gj = gradebook()
eq(sorted((gj.get('subjective') or {}).keys(), key=int), ['21', '22'], 'gradebook 带主观题表')
eq(gj.get('max'), {'auto': float(OBJ_MAX), 'subjective': 16.0, 'total': float(OBJ_MAX) + 16.0},
   '满分 = 客观 %d + 主观 16（4+6+6）' % OBJ_MAX)
row = row_of(gj, '2026010234')
eq(row['auto'], float(OBJ_MAX), '客观自动满分（用 s01 自己的答案当标准答案）')
eq(row['effective'], row['auto'], '还没打分时 主观分 = 0，总分 = 客观分')
pq21, pq22 = row['per_q']['21'], row['per_q']['22']
eq((pq21['subjective'], pq21['max'], pq21['graded']), (True, 10.0, False),
   '第 21 题：主观、满分 10、未阅')
eq(pq21['verdict'], '待阅卷', '未阅卷显示「待阅卷」（而不是 0/10 —— 那是真给了 0 分）')
eq(pq22['max'], 6.0, '第 22 题满分 6')
eq(pq21['auto'], None, '主观题没有「自动判定」这一说（auto 必须是 None，不能假装成错）')

print('\n=== E. 打分：两种模式（按小问 / 按整题）都能落库并算进总分 ===')
r = c.post('/api/grade', json={'sid': '2026010234', 'grading': {
    'overrides': {},
    'subs': {'21': [4, 5]},        # 小问模式：4/4 + 5/6
    'scores': {'22': 5.5},         # 整题模式：5.5/6
    'review': False, 'note': ''}})
ok(r.status_code == 200 and (r.get_json() or {}).get('ok'), '保存打分 200',
   str(r.get_json())[:140])
saved = (r.get_json() or {}).get('grading') or {}
eq(saved.get('subs'), {'21': [4.0, 5.0]}, '小问分落库（题号键归一化为字符串、分数转 float）')
eq(saved.get('scores'), {'22': 5.5}, '整题分落库')

gj = gradebook()
row = row_of(gj, '2026010234')
eq(row['auto'], float(OBJ_MAX), '客观自动分不受主观题打分影响')
eq(row['per_q']['21']['score'], 9.0, '第 21 题得分 = 4 + 5 = 9')
eq(row['per_q']['21']['verdict'], '9/10', '逐题显示 9/10')
eq([m['score'] for m in row['per_q']['21']['marks']], [4.0, 5.0],
   '逐小问明细带回来（前端要展示）')
eq([m['label'] for m in row['per_q']['21']['marks']], ['(1)', '(2)'], '小问名也带回来')
eq(row['per_q']['22']['score'], 5.5, '第 22 题得分 = 5.5')
eq(row['effective'], row['auto'] + 14.5, '总分 = 客观分 + (9 + 5.5)')

# 夹取：手滑多打一位不能让总分炸掉
r = c.post('/api/grade', json={'sid': '2026010235', 'grading': {
    'subs': {'21': [400, 900]}, 'scores': {'22': 999}}})
eq((r.get_json() or {}).get('grading', {}).get('scores'), {'22': 999.0},
   '接口原样收下（不在入口截断，免得老师不知道自己的输入被改了）')
row2 = row_of(gradebook(), '2026010235')
eq(row2['per_q']['21']['score'], 10.0, '算分时小问分被夹到满分（4 + 6）')
eq(row2['per_q']['22']['score'], 6.0, '算分时整题分被夹到满分 6')
eq(row2['effective'], row2['auto'] + 16.0, '夹取后总分 = 客观 + 主观满分')

# 没配小问的题给了小问分 → 扫描端不认（口径由模板决定，不由请求决定）
r = c.post('/api/grade', json={'sid': '2026010235', 'grading': {'subs': {'22': [6]}}})
eq((r.get_json() or {}).get('grading', {}).get('subs'), {'22': [6.0]}, '落库不做业务校验')
row3 = row_of(gradebook(), '2026010235')
eq(row3['per_q']['22']['score'], 0.0, '第 22 题按整题模式算 → 小问分被忽略，得 0')

# 脏数据不该把整份成绩单变成 nan
r = c.post('/api/grade', json={'sid': '2026010235', 'grading': {
    'scores': {'21': 'abc', '22': None}}})
eq((r.get_json() or {}).get('grading', {}).get('scores'), {}, '非数字分数在入口就被丢掉')
row4 = row_of(gradebook(), '2026010235')
ok(row4['effective'] == row4['effective'], '总分不是 nan（NaN 会让整列数字都废掉）',
   str(row4['effective']))
eq(row4['effective'], row4['auto'], '丢掉脏数据后回到「只有客观分」')

print('\n=== F. 导出：客观分 / 主观分 / 总分三列 ===')
c.post('/api/grade', json={'sid': '2026010234',
                           'grading': {'subs': {'21': [4, 5]}, 'scores': {'22': 5.5}}})
r = c.post('/api/export.csv', data={'key': KEY, 'graded': '1'})
lines = [l for l in r.data.decode('utf-8-sig').strip().splitlines() if l.strip()]
ok(r.status_code == 200, '导出 200')
ok(lines[0].endswith(',客观分,主观分,总分'), '表头末尾是 客观分/主观分/总分', lines[0][-30:])
eq(r.headers.get('X-Score-Max'), '%s/16.0/%s' % (float(OBJ_MAX), float(OBJ_MAX) + 16),
   '响应头带上三档满分（老师核对卷面总分用）')
head = lines[0].split(',')
zhang = next(l for l in lines[1:] if '2026010234' in l).split(',')
eq(float(zhang[head.index('主观分')]), 14.5, 'CSV 主观分 = 9 + 5.5')
eq(float(zhang[head.index('客观分')]), float(OBJ_MAX), 'CSV 客观分与成绩单一致')
eq(float(zhang[head.index('总分')]), float(OBJ_MAX) + 14.5, 'CSV 总分 = 客观 + 主观')
eq(zhang[head.index('21')], '9', '第 21 题那一列直接是该题得分（主观题没有字母可给）')
eq(zhang[head.index('22')], '5.5', '第 22 题那一列是该题得分')
ok(zhang[head.index('1')].isalpha() and len(zhang[head.index('1')]) <= 2,
   '客观题列仍是答案字母（没被主观题的改动带歪）', zhang[head.index('1')])

print('\n=== G. 统计：主观题不进选项分布，单独出平均分 ===')
r = c.post('/api/stats', json={'key': KEY})
sm = r.get_json() or {}
eq(r.status_code, 200, '统计接口 200')
ok(all(x['no'] not in (21, 22) for x in sm.get('questions') or []),
   '选项分布表里没有主观题（否则会多出一行「0 人作答」的假空行）',
   str([x['no'] for x in sm.get('questions') or []])[:60])
subq = {x['no']: x for x in ((sm.get('subjective') or {}).get('questions') or [])}
ok(21 in subq and 22 in subq, '主观题在主观题汇总里', str(sorted(subq)))
eq(subq[21]['points'], 10.0, '第 21 题满分 10')
eq(subq[21]['graded'], 1, '第 21 题已阅 1 份')
eq(subq[21]['avg'], 9.0, '第 21 题平均 9 分')
eq(subq[22]['avg'], 5.5, '第 22 题平均 5.5 分')
eq((sm.get('subjective') or {}).get('max'), 16.0, '主观题满分合计 16')
zh = next(x for x in sm['sheets'] if '张伟明' in x['name'])
eq(zh['subMax'], 16.0, '逐人带上主观满分（前端要算总分分母）')
eq(zh['subScore'], 14.5, '逐人主观得分 14.5')
li = next(x for x in sm['sheets'] if '李思' in x['name'])
eq(li['subScore'], 0.0, '没打分的考生主观得分 0（脏数据已经被清掉）')

print('\n=== H. 老用法（纯选择题模板 → 整套流程）一个字都不能变 ===')
# 换模板会**清空已识别结果**（这是对的：模板换了题号就对不上了）。
# 所以这里开一个全新的考试来跑「老用户」路径，免得把上面那套主观题数据冲掉。
r = c.post('/api/exams', json={'name': '纯选择题考试'})
ok(r.status_code == 200, '新建考试', str(r.get_json())[:120])
eid = (r.get_json() or {}).get('exam', {}).get('id')
ok(eid is not None, '拿到新考试 id')


def upload_tpl2(data):
    return c.post('/api/template', data={'file': (io.BytesIO(data), 'template.json'),
                                        'exam_id': str(eid)},
                  content_type='multipart/form-data')


r = upload_tpl2(bubble_template())
eq((r.get_json() or {}).get('summary', {}).get('subjective'), {}, '纯选择题模板：主观题为空')
c.post('/api/answer-key', json={'key': KEY, 'exam_id': eid})
r = c.post('/api/batch', data={'files': (io.BytesIO(zip_main), '一个班.zip'),
                               'exam_id': str(eid)},
           content_type='multipart/form-data')
eq(len((r.get_json() or {}).get('students') or []), 2, '老路径批量上传照旧')
gj = c.get('/api/gradebook?exam_id=%d' % eid).get_json() or {}
eq(gj.get('subjective'), {}, 'gradebook 主观题为空对象而不是 None', str(gj.get('subjective')))
eq(gj.get('max'), {'auto': float(OBJ_MAX), 'subjective': 0.0, 'total': float(OBJ_MAX)},
   '满分退回纯客观（没有主观题时不凭空多出分母）')
row = row_of(gj, '2026010234')
ok(all(not v.get('subjective') for v in row['per_q'].values()), '没有题被标成主观题')
eq(row['effective'], row['auto'], '总分 = 客观分')
r = c.post('/api/export.csv', data={'key': KEY, 'graded': '1', 'exam_id': str(eid)})
lines = [l for l in r.data.decode('utf-8-sig').strip().splitlines() if l.strip()]
ok(lines[0].endswith(',复核分'), '没有主观题时仍是单列「复核分」', lines[0][-20:])
eq(r.headers.get('X-Score-Max'), None, '没有主观题时不再是三列、也不加满分响应头')
eq(c.post('/api/stats', json={'key': KEY, 'exam_id': eid}).status_code, 200, '统计接口照旧 200')
eq((c.post('/api/stats', json={'key': KEY, 'exam_id': eid}).get_json() or {})
   .get('subjective', {}).get('questions'), [], '没有主观题时汇总列表是空数组（不是缺字段）')

print()
if FAILS:
    print(f'\u26a0\ufe0f  {len(FAILS)} 项未通过：')
    for f in FAILS:
        print('   -', f)
    sys.exit(1)
print('\U0001f389 主观题阅卷链路全部通过')
