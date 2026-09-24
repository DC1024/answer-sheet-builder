# 批量上传 / 归组 / 名单匹配的离线自检：不依赖浏览器、不依赖服务、不依赖网络。
#
#   python tests/test_batch.py
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import batch as bt      # noqa: E402

fails = 0


def ok(c, m):
    global fails
    print(('  ✅ ' if c else '  ❌ ') + m)
    if not c:
        fails += 1


def eq(got, want, label):
    ok(got == want, f'{label}（期望 {want!r}，实测 {got!r}）')


PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32      # 够用的假 PNG：batch 不解码图像


def mkzip(entries):
    """entries: [(内部路径, bytes 或 str)]"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in entries:
            zf.writestr(name, data if isinstance(data, bytes) else data.encode('utf-8'))
    return buf.getvalue()


print('=== A. 路径解析：目录名 / 文件名 / 页序提示 ===')
cases = [
    ('2026010234/正面.png', ('2026010234', 0)),
    ('2026010234/反面.png', ('2026010234', 1)),
    ('2026010234/1.png', ('2026010234', 0)),
    ('2026010234/2.png', ('2026010234', 1)),
    ('2026010234/1_1.png', ('2026010234', 0)),
    ('2026010234_1.png', ('2026010234', 0)),
    ('2026010234_2.png', ('2026010234', 1)),
    ('2026010234_p2.png', ('2026010234', 1)),
    ('2026010234.png', ('2026010234', None)),
    ('张伟明-2026010234.png', ('2026010234', None)),
    ('高二3班/2026010234/正.png', ('2026010234', 0)),
    ('s01.png', ('s01', None)),
    ('第1页.png', ('第1页', 0)),
]
for path, want in cases:
    eq(bt.parse_entry(path), want, path)

print('\n=== B. zip 解包：嵌套目录 / 垃圾文件 / 名单 / 嵌套 zip ===')
zf = mkzip([
    ('2026010234/正面.png', PNG),
    ('2026010234/反面.png', PNG),
    ('2026010235/正面.png', PNG),
    ('__MACOSX/._2026010234', b'junk'),
    ('.DS_Store', b'junk'),
    ('名单.csv', '考号,姓名,班级\n2026010234,张伟明,高三(12)班\n2026010235,李思,高三(12)班\n'),
    ('readme.txt', '这是一份说明，不是名单'),
])
imgs, rosts, nzip = bt.unpack([('scan.zip', 'scan.zip', zf)])
eq(nzip, 1, '识别到 1 个 zip')
eq(len(imgs), 3, '解出 3 张图（垃圾文件已剔除）')
ok(all('MACOSX' not in i[0] and 'DS_Store' not in i[0] for i in imgs), 'macOS 垃圾文件被剔除')
ok(any(r[0] == '名单.csv' for r in rosts), '名单 csv 被识别')

# zip 套 zip：真实场景里学生按「一人一个压缩包」交，再打成一个总包
inner = mkzip([('2026010236/正面.png', PNG)])
outer = mkzip([('2026010234/正面.png', PNG), ('学生包/nested.zip', inner)])
imgs_n, _, nzip_n = bt.unpack([('all.zip', 'all.zip', outer)])
eq(nzip_n, 2, '嵌套 zip 被递归展开')
ok(any('2026010236' in i[0] for i in imgs_n), '嵌套 zip 里的图被解出')

# 直接拖一整个文件夹（浏览器给的相对路径）
imgs_f, _, nzip_f = bt.unpack([('高二3班/2026010234/正面.png', '正面.png', PNG),
                               ('高二3班/2026010234/反面.png', '反面.png', PNG)])
eq(nzip_f, 0, '文件夹上传没有 zip')
eq(len(imgs_f), 2, '文件夹里的图被收下')

print('\n=== C. 归组：多页归到同一考号 ===')
students = bt.group(imgs)
eq([s['sid'] for s in students], ['2026010234', '2026010235'], '两个学生（按考号自然序）')
s1 = students[0]
eq([p['page'] for p in s1['pages']], [0, 1], '2026010234 两页，页序 0/1')
eq([p['name'] for p in s1['pages']], ['正面.png', '反面.png'], '正面排在前')

print('\n=== D. 名单解析 ===')
roster, cols = bt.parse_roster('\ufeff考号,姓名,班级\n2026010234,张伟明,高三(12)班\n2026010235,李思,高三(12)班\n')
eq(len(roster), 2, '解析出 2 人（含 BOM 也能解）')
eq(roster['2026010234'], {'name': '张伟明', 'cls': '高三(12)班'}, '姓名班级正确')
eq(cols.get('sid'), '考号', '识别到考号列名')

# GBK（Windows Excel 导出的 CSV 常见编码）
gbk = '学号\t学生姓名\t行政班\n2026010234\t张伟明\t高三(12)班\n'.encode('gbk')
roster_gbk, cols_gbk = bt.parse_roster(bt._read_text(gbk))
eq(roster_gbk['2026010234']['name'], '张伟明', 'GBK + Tab 分隔也能解')
eq(cols_gbk.get('cls'), '行政班', '识别到「行政班」是班级列')

# 表头别名 + 干扰列
roster2, _ = bt.parse_roster('姓名,准考证号,班级排名,行政班\n张伟明,2026010234,3,高三(12)班\n')
eq(roster2['2026010234'], {'name': '张伟明', 'cls': '高三(12)班'},
   '「班级排名」不会被误当成「班级」')

# 没有考号列 → 明确报错，不静默产出空名单
try:
    bt.parse_roster('姓名,分数\n张伟明,90\n')
    ok(False, '没有考号列时应报错')
except bt.BatchError as e:
    ok('考号' in str(e), f'没有考号列时明确报错：{e}')

print('\n=== E. 匹配：命中 / 不在名单 / 重复 / 未交 ===')
rost = {'2026010234': {'name': '张伟明', 'cls': '高三(12)班'},
        '2026010235': {'name': '李思', 'cls': '高三(12)班'},
        '2026010236': {'name': '王五', 'cls': '高三(12)班'}}
stus, warns = bt.match(students, rost)
ok(all(s['matched'] for s in stus), '两个学生都匹配上')
eq(stus[0]['name'], '张伟明', '姓名已贴上')
ok(any('没交卷' in w and '2026010236' in w for w in warns),
   f'未交卷的人被点名：{[w for w in warns if "没交卷" in w]}')

# 不在名单里
stus2, warns2 = bt.match(bt.group([('9999999999.png', '9999999999.png', PNG)]), rost)
ok(stus2[0]['matched'] is False, '不在名单里 → matched=False')
ok(any('不在名单里' in i for i in stus2[0]['issues']), '标出「考号不在名单里」')

# 重复考号：同一考号出现在不同目录（同一目录下的多文件是正常的多页，不算重复）
dup_imgs = [('2026010234/正面.png', '正面.png', PNG), ('别的目录/2026010234.png', '2026010234.png', PNG)]
stus3, warns3 = bt.match(bt.group(dup_imgs), rost)
ok(any('重复' in i for i in stus3[0]['issues']), '跨目录同考号 → 标出「疑似重复」')
ok(any('重复' in w for w in warns3), f'重复考号进 warnings：{warns3}')

# 同一目录下多个文件 = 正常多页，不该被当成重复
sane = [('2026010234/正面.png', '正面.png', PNG), ('2026010234/反面.png', '反面.png', PNG)]
stus_sane, _ = bt.match(bt.group(sane), rost)
ok(not any('重复' in i for i in stus_sane[0]['issues']), '同一目录多文件不误报重复')

# 没导名单 → matched=None（不是 False，避免误报「不在名单」）
stus4, _ = bt.match(bt.group(imgs), {})
ok(all(s['matched'] is None for s in stus4), '未导入名单时 matched=None')

# 人工补录优先于名单
stus5, _ = bt.match(bt.group(imgs), rost, overrides={'2026010234': {'name': '张伟明(改)'}})
eq(stus5[0]['name'], '张伟明(改)', '人工补录覆盖名单')

print('\n=== F. 多页答案合并 ===')
pages = [
    {'questions': [{'no': 1, 'answer': 'D', 'flag': 'ok'}, {'no': 2, 'answer': 'C', 'flag': 'ok'}]},
    {'questions': [{'no': 3, 'answer': None, 'flag': 'blank'}, {'no': 4, 'answer': 'A', 'flag': 'ok'}]},
]
ans, conf = bt.merge_answers(pages)
eq(list(ans.keys()), [1, 2, 3, 4], '两页合并后题号 1-4')
eq(conf, [], '无冲突')
ok(ans[3]['answer'] is None and ans[3]['flag'] == 'blank', '未填题保留 blank')

conflict = [
    {'questions': [{'no': 1, 'answer': 'D', 'flag': 'ok'}]},
    {'questions': [{'no': 1, 'answer': 'B', 'flag': 'ok'}]},
]
ans2, conf2 = bt.merge_answers(conflict)
eq(conf2, [1], '同题号不同答案 → 报冲突')

print('\n=== G. 页序：无提示时按文件名字典序 ===')
imgs2 = [('2026010234/p3.png', 'p3.png', PNG), ('2026010234/1.png', '1.png', PNG),
         ('2026010234/2.png', '2.png', PNG)]
g2 = bt.group(imgs2)
eq([p['page'] for p in g2[0]['pages']], [0, 1, 2], '1/2 有提示排前，p3 接在后面')

imgs3 = [('2026010234_c.png', '2026010234_c.png', PNG),
         ('2026010234_a.png', '2026010234_a.png', PNG),
         ('2026010234_b.png', '2026010234_b.png', PNG)]
g3 = bt.group(imgs3)
eq([p['name'] for p in g3[0]['pages']],
   ['2026010234_a.png', '2026010234_b.png', '2026010234_c.png'], '无提示时按名字自然序')

imgs4 = [('2026010234_10.png', '2026010234_10.png', PNG),
         ('2026010234_2.png', '2026010234_2.png', PNG)]
g4 = bt.group(imgs4)
eq([p['page'] for p in g4[0]['pages']], [1, 9], '自然序：_2 在 _10 前（不是字符串序）')

print('\n=== H. 反复套名单（老师补录后重新匹配）===')
# 服务端会反复调 match()：先按名单匹配 → 老师补录姓名 → 再套一次。
# issues 必须每次重建，否则问题会一轮一轮往上堆。
reuse = bt.group(dup_imgs)
_, w_a = bt.match(reuse, rost)
n_a = len(reuse[0]['issues'])
_, w_b = bt.match(reuse, rost, overrides={'2026010234': {'name': '张伟明', 'cls': '高三(12)班'}})
n_b = len(reuse[0]['issues'])
eq(n_b, n_a, f'重新匹配后问题数不变（{n_a} → {n_b}）')
ok(reuse[0]['manual'], '人工补录后 manual=True')
ok(any('重复' in i for i in reuse[0]['issues']), '归组阶段的问题在重建后仍在')

# 识别阶段的问题（pageIssues）要被带进来，同样不能重复累加
reuse[0]['pageIssues'] = ['第 1 面识别失败：无法解码图片']
bt.match(reuse, rost)
eq(len(reuse[0]['issues']), n_a + 1, 'pageIssues 被计入问题列表')
bt.match(reuse, rost)
eq(len(reuse[0]['issues']), n_a + 1, '再套一次不重复累加 pageIssues')

# 名单换成空的 → matched 回到 None，而「不在名单里」这类结论要能被清掉
bt.match(reuse, {})
ok(reuse[0]['matched'] is None, '清空名单后不再报「不在名单里」')
ok(not any('不在名单里' in i for i in reuse[0]['issues']), '旧的「不在名单」结论已被清掉')

print('\n=== I. 卷面考号：校正分组 / 合并散页 / 缺位补全 / 错一位建议 ===')
# 现实里不会有老师把 50 个文件改名成考号，也不会给每个学生发二维码。
# 所以「卷面考号」是主身份来源 —— 但它必须在识别之后才拿得到，
# 于是分组要能**事后校正**。这一节把校正的几条规矩钉住。


def png_page(sid_text=None, ans=None, page=None, hinted=True, ok=True, source='p.png'):
    """一页的识别结果（假的，只为跑归组逻辑）"""
    t = sid_text or ''
    sid = ({'text': t, 'digits': len(t), 'ok': '?' not in t,
            'filled': len(t) - t.count('?'), 'flags': ['ok'] * len(t)} if t else None)
    return {'ok': ok, 'name': 'p.png', 'page': page, 'hinted': hinted, 'source': source,
            'sid': sid,
            'questions': [{'no': k, 'answer': v, 'flag': 'ok'} for k, v in (ans or {}).items()]}


def run(images, sid_of=None, ans_of=None, roster=None):
    """照 server.batch_api 的顺序走一遍：group → 逐页识别（用假结果）→ regroup → match"""
    roster = roster or {}
    students = bt.group(images)
    for stu in students:
        pages = [png_page((sid_of or {}).get(p['relpath']), (ans_of or {}).get(p['relpath']),
                          page=p['page'], hinted=p['hinted'], source=p['relpath'])
                 for p in stu['pages']]
        stu['pages'] = pages
        stu['answers'], stu['conflicts'] = bt.merge_answers(pages)
        stu['pageIssues'] = []
        stu['source'] = '、'.join(p['source'] for p in pages)
    return bt.match(bt.regroup(students, roster), roster)


def img(name):
    return (name, name, PNG)


# --- 先分清「文件名里的数字是不是考号」 -----------------------------------
# 相机命名的 IMG_0001 里有 "0001"，扫描件里常带 "20240925_1030" 时间戳。
# 这些如果被当成考号，就会和卷面读到的考号「打架」，于是系统拒绝归组 ——
# 越是不按规范命名的老师越用不了，正好和「不想改名」的初衷相反。
eq(bt.file_sid_strong('IMG_0001.png', '0001'), False, 'IMG_0001.png 里的数字不算考号')
eq(bt.file_sid_strong('scan_0012.png', '0012'), False, 'scan_0012.png 不算')
eq(bt.file_sid_strong('扫描件_20240925_1030.png', '20240925'), False, '时间戳不算考号')
eq(bt.file_sid_strong('2026010234_1.png', '2026010234'), True, '2026010234_1.png 里的算考号')
eq(bt.file_sid_strong('2026010234.png', '2026010234'), True, '整段名字就是考号')
eq(bt.file_sid_strong('2026010234/正面.png', '2026010234'), True, '写在目录名里的算考号')
eq(bt.file_sid_strong('张伟明-2026010234.png', '2026010234'), True, '「姓名-考号」算考号')
eq(bt.file_sid_strong('IMG_0001.png', '0001', roster={'0001': {}}), True,
   '名单里真有这个人 → 反过来认可它（命名习惯不一致时以名单为准）')


# --- 文件名里没有考号（IMG_0001 这种）→ 用卷面读到的人 ---
stus, _ = run([img('IMG_0001.png'), img('IMG_0002.png')],
              {'IMG_0001.png': '2026010234', 'IMG_0002.png': '2026010234'},
              {'IMG_0001.png': {1: 'A', 2: 'B'}, 'IMG_0002.png': {3: 'C', 4: 'D'}})
eq(len(stus), 1, '两张散图按卷面考号并成一位考生（不必改名）')
eq(stus[0]['sid'], '2026010234', '考号取自卷面')
eq(stus[0]['sidSource'], 'sheet', '标出「考号来自卷面」')
eq(len(stus[0]['pages']), 2, '两页都归到这一位')
eq(sorted(stus[0]['answers']), [1, 2, 3, 4], '两页答案合并，没有互相覆盖')
ok('IMG_0002.png' in (stus[0]['note'] or ''), '说明里写清是哪几张图并的')

# --- 文件名与卷面一致 → 互证，无事发生 ---
stus, _ = run([img('2026010234.png')], {'2026010234.png': '2026010234'})
eq(stus[0]['sidSource'], 'both', '文件名与卷面一致时标为互证')
eq(stus[0]['issues'], [], '两边一致就没有要人工看的问题')

# --- 文件名与卷面不一致 → 不擅自改，两边都摆出来 ---
stus, _ = run([img('2026010234.png')], {'2026010234.png': '2026010235'})
eq(stus[0]['sid'], '2026010234', '冲突时保持文件名归组（不擅自把卷子记到别人名下）')
eq(stus[0]['sidSource'], 'conflict', '标为冲突待确认')
ok(any('不一致' in i for i in stus[0]['issues']), '冲突进「待确认」列表')

# --- 同一份卷子两页读串了 → 谁的都不信 ---
stus, _ = run([img('2026010234_1.png'), img('2026010234_2.png')],
              {'2026010234_1.png': '2026010234', '2026010234_2.png': '2026010235'})
eq(len(stus), 1, '两页读串了仍按文件名合成一份')
eq(stus[0]['sheetSid'], None, '拿不准时 sheetSid 为 None（不猜）')
ok(stus[0]['sheetSidInfo']['agree'] is False, '记下「两页读得不一样」而不是「没读到」')

# --- 卷面缺位：名单里唯一符合才敢补 ---
roster1 = {'2026010234': {'name': '张伟明', 'cls': '高三(12)班'},
           '2026010235': {'name': '李小明', 'cls': '高三(12)班'}}
stus, _ = run([img('IMG_0001.png')], {'IMG_0001.png': '20?6010234'}, roster=roster1)
eq(stus[0]['sid'], '2026010234', '卷面缺一位 + 名单里唯一符合 → 自动补全')
eq(stus[0]['sidSource'], 'roster', '标出「名单补全缺位」')
eq(stus[0]['matched'], True, '补全后能对上名单的人')
eq(stus[0]['name'], '张伟明', '姓名也接上了')

roster2 = {'2026010234': {'name': '张伟明', 'cls': ''},
           '2096010234': {'name': '王五', 'cls': ''}}
stus, _ = run([img('IMG_0001.png')], {'IMG_0001.png': '20?6010234'}, roster=roster2)
eq(stus[0]['sid'], '20?6010234', '两个人符合 → 不猜，保留缺位')
eq(stus[0]['sidSource'], 'sheet-partial', '标为「卷面有缺位」')
ok(any('人工认领' in i for i in stus[0]['issues']), '缺位且有多个候选人 → 进待确认列表')

# --- 错一位数字：指出是哪一位、应该是几 ---
stus, warns = run([img('IMG_0001.png')], {'IMG_0001.png': '2026010239'},
                  roster={'2026010234': {'name': '张伟明', 'cls': '高三(12)班'}})
eq(stus[0]['sid'], '2026010239', '读到的考号照原样保留（不能替学生改）')
eq(stus[0]['sidSuggest'], ['2026010234'], '给出「只差一位」的候选')
ok(any('只差第 10 位' in i for i in stus[0]['issues']), '问题里写清是哪一位错')
ok(any('只差一位' in w for w in warns), '汇总警告里也提一句，老师不用逐张看')

# --- 单测：resolve_sid / sheet_sids 的边界 ---
eq(bt.resolve_sid('20?6010234', {}), (None, []), '没有名单时不去猜缺位')
eq(bt.resolve_sid('2026010234', roster1), (None, []), '没有缺位就没有可补的')
eq(bt.suggest_sid('2026010234', roster1), [], '考号本来就在名单里 → 没有建议')
eq(bt.suggest_sid('20?6010234', roster1), [], '还带着缺位 → 不做错一位建议')
eq(bt.suggest_sid('2026010234', {}), [], '没有名单 → 没有建议')
eq(bt.sheet_sids([{'sid': None}, {'ok': False}])[0], None, '一页都没读出考号 → None')
eq(bt.sheet_sids([{'sid': {'text': '2?26?1?234'}}])[0], None, '缺位太多（认不出是谁）→ None')

# --- 页码是不是文件名提示的，要记下来（多面模板靠它提醒可能排错页）---
g = bt.group([('2026010234/正面.png', '正面.png', PNG), ('2026010234/x.png', 'x.png', PNG)])
eq([p['hinted'] for p in g[0]['pages']], [True, False], '「页码来自文件名提示」被记下来')

print('\n' + ('🎉 批量上传全部通过' if fails == 0 else f'⚠️ {fails} 项未通过'))
sys.exit(0 if fails == 0 else 1)
