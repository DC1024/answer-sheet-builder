# 服务层测试：用 Flask 测试客户端直接打接口，不需要部署、不需要起服务。
#
#   python tests/test_service.py
#
# 这里只查「接线」—— 路由、字段、归组、名单匹配、多页合并、页序越界、统计导出列。
# 识别精度不在这里管：精度由 tests/test_omr.py（离线，对着夹具）和
# tests/e2e_service.py（对着真容器里的 opencv 4.9）负责。
import io
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app import server                          # noqa: E402
from tests import _fixtures                     # noqa: E402

FIX = _fixtures.FIX
FAILS = []
try:
    import cv2
    CV2 = cv2.__version__
except Exception:
    CV2 = '?'


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


ROSTER = ('考号,姓名,班级\n'
          '2026010234,张伟明,高三(12)班\n'
          '2026010235,李思,高三(12)班\n'
          '2026010236,王五,高三(12)班\n'
          '2026010299,赵六,高三(12)班\n')

EXPECTED = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))['students']
c = server.app.test_client()
print(f'OpenCV {CV2}（容器里是 4.9.0.80，精度以端到端测试为准）')


def upload_template():
    return c.post('/api/template', data={'file': (io.BytesIO(img('template.json')), 'template.json')},
                  content_type='multipart/form-data')


def post_batch(zip_bytes, name='一个班.zip', **form):
    data = {'files': (io.BytesIO(zip_bytes), name)}
    data.update(form)
    return c.post('/api/batch', data=data, content_type='multipart/form-data')


print('\n=== A. 前置条件：没模板就明确拒绝 ===')
r = c.post('/api/batch', data={'files': (io.BytesIO(mkzip([]) or b'x'), 'x.zip')},
           content_type='multipart/form-data')
eq(r.status_code, 400, '没上传模板 → 400')
ok('阅卷模板' in (r.get_json() or {}).get('error', ''), '报错提示指向模板')

r = upload_template()
ok(r.status_code == 200 and (r.get_json() or {}).get('ok'), '模板上传成功')
summary = (r.get_json() or {}).get('summary') or {}
eq(summary.get('questionCount'), 20, '模板 20 题')
eq(len(summary.get('pages') or []), 1, '模板 1 面（越界用例要用到这一点）')

print('\n=== B. 批量上传：zip + 内嵌名单 + 垃圾文件 ===')
zip_main = mkzip([
    ('一个班/2026010234/正面.png', img('s01.png')),
    ('一个班/2026010235/正面.png', img('s02.png')),
    ('一个班/__MACOSX/._2026010235', b'junk'),
    ('一个班/2026010235/._正面.png', b'junk'),
    ('一个班/.DS_Store', b'junk'),
    ('一个班/2026010236.png', img('s03.png')),
    ('一个班/2026010237.png', img('s04.png')),
    ('一个班/名单.csv', ROSTER.encode('utf-8')),
])
r = post_batch(zip_main)
j = r.get_json() or {}
ok(r.status_code == 200, '批量接口 200', f'HTTP {r.status_code} {str(j)[:120]}')
stus = j.get('students') or []
eq(len(stus), 4, '归组出 4 位考生')
eq((j.get('stats') or {}).get('images'), 4, '垃圾文件被跳过（图片数 = 4）')
eq([s['sid'] for s in stus], ['2026010234', '2026010235', '2026010236', '2026010237'],
   '按考号自然序排列')
eq((j.get('roster') or {}).get('count'), 4, 'zip 内嵌名单被识别')

m = {s['sid']: s for s in stus}
ok(m['2026010234']['name'] == '张伟明' and m['2026010234']['cls'] == '高三(12)班',
   '姓名+班级贴上', str(m['2026010234'].get('name')))
ok(m['2026010234']['matched'] is True, '名单内 → matched=True')
ok(m['2026010237']['matched'] is False
   and any('不在名单里' in i for i in m['2026010237']['issues']),
   '名单外 → matched=False 并进待确认队列', str(m['2026010237']['issues']))
warns = ' | '.join(j.get('warnings') or [])
ok('没交卷' in warns, '提示名单里没交卷的人', warns[:100])
ok('不在名单里' in warns, '提示有考号不在名单里', warns[:100])
eq(m['2026010234']['issues'], [], '正常考生没有问题项')
ok(all(s.get('sidSource') == 'both' for s in stus),
   '目录名里的考号与卷面涂的一致 → 互证',
   str([(s['sid'], s.get('sidSource')) for s in stus]))
ok(all((p.get('sid') or {}).get('text') == s['sid'] for s in stus for p in s['pages']),
   '每一页都从卷面上读到了考号',
   str([(s['sid'], [p.get('sid') for p in s['pages']]) for s in stus][:1]))

ok(all(p.get('ok') and p.get('overlay') for s in stus for p in s['pages']),
   '每一面都识别成功且校对图落盘',
   str([(s['sid'], [p.get('overlay') for p in s['pages']]) for s in stus]))
pid = next(p['id'] for s in stus for p in s['pages'] if p.get('id'))
r = c.get(f'/api/overlay/{pid}.png')
ok(r.status_code == 200 and r.data[:8] == b'\x89PNG\r\n\x1a\n', '校对图可取且是合法 PNG',
   f'HTTP {r.status_code}, {len(r.data)} bytes')

print('\n=== C. 答案：批量路径与单张路径必须一致 ===')
SID2FIX = {'2026010234': 's01', '2026010235': 's02', '2026010236': 's03', '2026010237': 's04'}
tot = cor = 0
mismatch = []
for s in stus:
    exp = (EXPECTED.get(SID2FIX.get(s['sid'], '')) or {}).get('answers') or {}
    for no, want in exp.items():
        if want is None:
            continue
        tot += 1
        # 答案字典经过 JSON 后键是字符串（浏览器侧也一样）
        got = (s.get('answers') or {}).get(str(no), {}).get('answer')
        if got == want:
            cor += 1
        else:
            mismatch.append(f"{s['sid']}#{no}:{got}≠{want}")
acc = cor / tot * 100 if tot else 0
ok(acc >= 95, f'平均正确率 {acc:.1f}% (≥95%)', f'{cor}/{tot} ' + ','.join(mismatch[:5]))
eq((stus[0]['answers'].get('3') or {}).get('flag'), 'blank', '第 3 题（未涂）保留 blank')
eq((stus[0]['answers'].get('8') or {}).get('flag'), 'faint', '第 8 题（浅涂）保留 faint')
eq((stus[0]['answers'].get('15') or {}).get('flag'), 'multi', '第 15 题（涂两个）保留 multi')
eq(len(stus[0]['answers']), 20, '合并后题号覆盖 1-20')

print('\n=== D. 统计与导出（默认只针对最近一批）===')
r = c.post('/api/stats', json={'key': '1D 2C 4A 5D'})
sm = r.get_json() or {}
ok(r.status_code == 200, '统计接口 200')
eq(sm.get('sheetCount'), 4, '统计只覆盖这一批 4 位考生')
ok(any('张伟明' in (x.get('name') or '') for x in sm.get('sheets') or []),
   '统计里带姓名', str([x['name'] for x in sm.get('sheets') or []])[:90])
zw = next(x for x in sm['sheets'] if '张伟明' in x['name'])
eq(zw['score'], 4, '张伟明按 1D 2C 4A 5D 判 4 分')

r = c.post('/api/export.csv', data={'key': '1D 2C 4A 5D'})
lines = [l for l in r.data.decode('utf-8-sig').strip().splitlines() if l.strip()]
ok(lines[0].startswith('考号,姓名,班级,文件,1,2,'), 'CSV 表头带考号/姓名/班级', lines[0][:70])
eq(len(lines), 5, 'CSV = 表头 + 4 位考生')
ok(lines[1].startswith('2026010234,张伟明,高三(12)班') and lines[1].endswith(',4'),
   '首行是考号最小的那位且得分正确', lines[1][:50] + ' … ' + lines[1][-6:])

print('\n=== E. 人工补录 / 名单单独导入（反复套名单不堆问题）===')
# 界面上的「重新套用」是发 JSON 体的（批量上传时则是表单字段）—— 两条路都得认
r = c.post('/api/batch/rematch', json={'overrides': {'2026010237': {'name': '补录同学',
                                                                 'cls': '高三(12)班'}}})
j2 = r.get_json() or {}
ok(r.status_code == 200, 'JSON 体传补录数据可用', f'HTTP {r.status_code} {str(j2)[:100]}')
fixed = next((s for s in j2.get('students') or [] if s['sid'] == '2026010237'), {})
eq(fixed.get('name'), '补录同学', '人工补录生效')
ok(fixed.get('manual') is True, '标记 manual')
# 补录姓名 = 老师已经确认过这个人 → matched 变 True、问题项清空，
# 但必须留下 manual 标记，界面上要能和「名单里匹配到的」区分开
ok(fixed.get('matched') is True, '补录后视为已确认', str(fixed.get('issues')))
eq(fixed.get('issues'), [], '补录后问题项清空（不是被掩盖，是真的解决了）')
ok('不在名单里' not in ' | '.join(j2.get('warnings') or []),
   '补录之后「有考号不在名单里」的警告随之消失',
   ' | '.join(j2.get('warnings') or []))
eq(len(fixed.get('answers') or {}), 20, '答案没被动过')
ok(next((s for s in j2.get('students') or [] if s['sid'] == '2026010234'), {})
   .get('manual') is False, '没补录的人不会被误标 manual')

r = c.post('/api/batch/rematch',
           data={'overrides': json.dumps({'2026010237': {'name': '表单补录'}})})
ok(next((s for s in (r.get_json() or {}).get('students') or [] if s['sid'] == '2026010237'),
        {}).get('name') == '表单补录', '表单字段传补录数据也可用')
r = c.post('/api/batch/rematch', data={'overrides': '{坏 JSON'})
eq(len((r.get_json() or {}).get('students') or []), 4, '坏 JSON 不会打挂接口（当没传处理）')

r = c.post('/api/roster', data={'file': (io.BytesIO(ROSTER.encode('utf-8')), '名单.csv')},
           content_type='multipart/form-data')
j3 = r.get_json() or {}
eq((j3.get('roster') or {}).get('count'), 4, '名单可单独导入并重新套用')
ok(next((s for s in j3.get('students') or [] if s['sid'] == '2026010237'), {})
   .get('matched') is False, '导入的名单里也没有 237 → 仍然待确认')

r = c.get('/api/roster.csv')
rl = [l for l in r.data.decode('utf-8-sig').strip().splitlines() if l.strip()]
eq(rl[0], '考号,姓名,班级,考号来源,页数,说明,备注', '名单对账表头（带考号来源）')
eq(len(rl), 5, '名单对账 4 人')
ok('卷面' in r.data.decode('utf-8-sig'), '对账表里写明考号是卷面读到的还是文件名里的',
   rl[1][:90])

r = c.post('/api/roster', data={'file': (io.BytesIO(b'\xe5\xa7\x93\xe5\x90\x8d,\xe5\x88\x86\xe6\x95\xb0\n'), 'x.csv')},
           content_type='multipart/form-data')
ok(r.status_code == 400 and '考号' in (r.get_json() or {}).get('error', ''),
   '没有考号列 → 400 且说明原因', str((r.get_json() or {}).get('error'))[:80])

print('\n=== F. 页序越界必须报错（不能静默夹到最后一页）===')
j4 = post_batch(mkzip([
    ('2026010234/正面.png', img('s01.png')),
    ('2026010234/反面.png', img('s02.png')),
]), name='多一页.zip').get_json() or {}
s4 = (j4.get('students') or [{}])[0]
pgs = s4.get('pages') or []
eq(len(pgs), 2, '两面都被列出（不是悄悄少一面）')
eq([p.get('ok') for p in pgs], [True, False], '只有第 1 面识别成功')
bad = next((p for p in pgs if not p.get('ok')), {})
ok('超出模板范围' in str(bad.get('error')), '越界那面明确报错', str(bad.get('error'))[:100])
ok(any('超出模板范围' in i for i in (s4.get('issues') or [])),
   '问题进到待确认队列', str(s4.get('issues'))[:120])
eq(len(s4.get('answers') or {}), 20, '第 1 面的答案仍然保留（一面出错不作废整份）')
ok('超出模板范围' in ' | '.join(j4.get('warnings') or [])
   or any('超出模板范围' in i for i in (s4.get('issues') or [])), '问题对外可见')

print('\n=== G. 单张扫描与批量的隔离 ===')
r = c.post('/api/scan', data={'files': (io.BytesIO(img('s05.png')), 's05.png'),
                              'pxPerMm': '8.0'},
           content_type='multipart/form-data')
js = r.get_json() or {}
eq(len(js.get('results') or []), 1, '单张扫描返回 1 份')
r = c.post('/api/stats', json={'key': '1D 2C 4A 5D'})
sm2 = r.get_json() or {}
eq(sm2.get('sheetCount'), 1, '统计跟随最近一次操作（单张扫描后只统计这 1 份）')

r = c.post('/api/batch', data={'files': (io.BytesIO(mkzip([('空目录/', b'')])), '空.zip')},
           content_type='multipart/form-data')
ok(r.status_code == 400 and '没找到图片' in (r.get_json() or {}).get('error', ''),
   '压缩包里没图片 → 400 且说明原因', str((r.get_json() or {}).get('error'))[:80])

print('\n=== H. 文件夹上传（paths 还原目录结构）===')
# 浏览器选文件夹时每个文件都带 webkitRelativePath；服务端靠 paths 按序还原。
# 两个文件同名 —— 只能靠目录区分，正好验证确实用了 paths 而不是文件名。
r = c.post('/api/batch',
           data={'pxPerMm': '8.0',
                 'paths': ['一班/2026010234/正面.png', '一班/2026010235/正面.png'],
                 'files': [(io.BytesIO(img('s01.png')), '正面.png'),
                           (io.BytesIO(img('s02.png')), '正面.png')]},
           content_type='multipart/form-data')
j5 = r.get_json() or {}
ok(r.status_code == 200, '文件夹上传 200', str(j5)[:120])
fs = j5.get('students') or []
eq([s['sid'] for s in fs], ['2026010234', '2026010235'], '两个同名文件靠目录名区分')
ok(all(p.get('ok') for s in fs for p in s['pages']), '两面都识别成功')
ok(all('一班/202601023' in (p.get('source') or '') for s in fs for p in s['pages']),
   '保留原始相对路径便于溯源', str([p.get('source') for s in fs for p in s['pages']]))

print('\n=== I. 文件名里没有考号 → 按卷面考号归组（不必给学生发码、也不必改名）===')
# 相机/扫描仪命的 IMG_0001、扫描件_20240925_1030 里那串数字是序号/时间戳，不是考号。
# 只要卷面涂了考号，就该按卷面归组 —— 这是「不改造学生名单、不要求改名」能不能落地的关键。
z3 = mkzip([
    ('扫描/IMG_0001.png', img('s01.png')),
    ('扫描/IMG_0002.png', img('s02.png')),
    ('扫描/IMG_0003.png', img('s03.png')),
])
r = post_batch(z3, '扫描.zip')
j6 = r.get_json() or {}
ok(r.status_code == 200, '相机命名的散图批量上传 200', str(j6)[:120])
s6 = j6.get('students') or []
eq([s['sid'] for s in s6], ['2026010234', '2026010235', '2026010236'], '考号取自卷面填涂')
ok(all(s.get('sidSource') == 'sheet' for s in s6), '标出「考号来自卷面」',
   str([(s['sid'], s.get('sidSource')) for s in s6]))
ok(all('IMG_000' in (s.get('note') or '') for s in s6), '说明里写清是按哪个文件归的组',
   str([s.get('note') for s in s6][:2]))
ok(all('未能从文件名解析出考号' not in ' '.join(s.get('issues') or []) for s in s6),
   '不再报「解析不出考号」（已经由卷面认出来了）',
   str([s.get('issues') for s in s6][:2]))
eq(len(s6[0]['answers']), 20, '答案照样齐全')

print('\n' + '=' * 56)
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f in FAILS:
        print('   -', f)
    sys.exit(1)
print('🎉 服务层接口测试全部通过')
