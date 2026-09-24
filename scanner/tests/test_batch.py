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

print('\n' + ('🎉 批量上传全部通过' if fails == 0 else f'⚠️ {fails} 项未通过'))
sys.exit(0 if fails == 0 else 1)
