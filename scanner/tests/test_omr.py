# 阅卷核心测试：干净扫描 / 手机拍照模拟（透视+光照+噪声）/ 存疑标记 / 统计
#
#   python tests/test_omr.py
#
# 素材在 tests/fixtures/：6 份由真实制卡端渲染 + 模拟涂卡的答题卡（PNG）、
# 对应的阅卷模板、以及每份卷子的预期答案。手机拍照图由 _fixtures.photo_sim
# 在运行时现场合成，写进临时目录，不污染仓库。
import json
import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import omr            # noqa: E402
from app import stats as st    # noqa: E402
from tests import _fixtures    # noqa: E402

FIX = _fixtures.FIX

fails = 0
def ok(c, m):
    global fails
    print(('  ✅ ' if c else '  ❌ ') + m)
    if not c: fails += 1


def run_case(tpl, files, name, min_acc=1.0, px_per_mm=8.0, **kw):
    accs, flags = [], {}
    for f in sorted(files):
        # 手机图在临时目录（绝对路径），取 basename 才能对上 expected.json 的 s01/s02…
        exp = EXPECTED[os.path.splitext(os.path.basename(f))[0].replace('_phone', '')]
        img = cv2.imread(os.path.join(FIX, f) if not os.path.isabs(f) else f)
        r = omr.recognize(img, tpl, px_per_mm=px_per_mm, **kw)
        got = {q['no']: q['answer'] for q in r['questions']}
        flg = {q['no']: q['flag'] for q in r['questions']}
        n_right, n_total = 0, 0
        for no, want in exp.items():
            no = int(no)
            if want is None: continue
            n_total += 1
            if got.get(no) == want: n_right += 1
        accs.append(n_right / max(1, n_total))
        flags[os.path.basename(f)] = (flg.get(3), flg.get(8))
    acc = sum(accs) / len(accs)
    print(f'  {name}: 平均正确率 {acc * 100:.1f}%（{len(accs)} 份）')
    return acc, flags


def _load_overlay(r):
    import numpy as np
    return cv2.imdecode(np.frombuffer(r['overlayPng'], np.uint8), cv2.IMREAD_COLOR)


TPL = omr.load_template(open(os.path.join(FIX, 'template.json'), encoding='utf-8').read())
EXPECTED = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))
CLEAN = sorted(f for f in os.listdir(FIX) if f.startswith('s') and f.endswith('.png'))

print('=== A. 干净扫描（300dpi 级） ===')
acc_clean, flags_clean = run_case(TPL, CLEAN, '干净扫描')
ok(acc_clean >= 0.99, f'干净扫描准确率 {acc_clean * 100:.1f}% ≥ 99%')
ok(flags_clean[CLEAN[0]][0] == 'blank', '第 3 题（未涂）标记为 blank')
ok(flags_clean[CLEAN[0]][1] == 'faint', '第 8 题（浅涂）标记为 faint')

print('\n=== B. 手机拍照模拟（透视+明暗+模糊+噪声+JPEG） ===')
PHONE = [p for _, p in _fixtures.phone_variants(CLEAN)]
acc_phone, flags_phone = run_case(TPL, PHONE, '手机拍照模拟')
ok(acc_phone >= 0.95, f'拍照模拟准确率 {acc_phone * 100:.1f}% ≥ 95%')
ok(flags_phone[os.path.basename(PHONE[0])][1] == 'faint', '拍照图里第 8 题（浅涂）仍标为 faint')

print('\n=== C. 阈值容错：把填涂阈值调低后拍照图仍稳 ===')
acc_low, _ = run_case(TPL, PHONE, '低阈值拍照', fill_min=0.4, gap=0.12)
ok(acc_low >= 0.95, f'低阈值拍照准确率 {acc_low * 100:.1f}% ≥ 95%')

print('\n=== D. 汇总统计与判分 ===')
sheets = []
for f in CLEAN:
    r = omr.recognize(cv2.imread(os.path.join(FIX, f)), TPL, px_per_mm=8.0)
    sheets.append({'name': f, 'answers': {q['no']: {'answer': q['answer'], 'flag': q['flag']} for q in r['questions']}})
key = st.parse_key('1A 2B 3C 4D 5A 6B 7C 8D 9A 10B 11C 12D 13A 14B 15C 16D 17A 18B 19C 20D')
sm = st.summarize(sheets, [q['no'] for p in TPL['pages'] for q in p['questions']], key)
ok(sm['sheetCount'] == 6, f'汇总 6 份卷（实测 {sm["sheetCount"]}）')
ok(all('rate' in q for q in sm['questions']), '每题有正确率')
ok(sm['sheets'][0]['total'] == 20, f'个人满分 20（实测 {sm["sheets"][0]["total"]}）')
csv_rows = st.to_csv([[s['name'], s['score']] for s in sm['sheets']], ['name', 'score'])
ok(csv_rows.count('\n') == 7, f'CSV 行数正确（{csv_rows.count(chr(10))}）')

# 回归：标准答案里缺的题不能白送分（历史 bug：未作答 None == 无标准答案 None 被算成答对）
blank_answers = {1: {'answer': None, 'flag': 'blank'}, 2: {'answer': 'B', 'flag': 'ok'}}
ok(st.score(blank_answers, [1, 2], {2: 'B'}) == 1,
   '未作答且无标准答案的题不计分（满分应为 1）')

print('\n=== E. 光照归一化：降采样背景与原分辨率等价 ===')
# _lighting_normalize 为提速改成在 1/4 分辨率上估背景（原本 159×159 的椭圆闭运算
# 在 14M 像素上要 ~900ms，整条识别就卡在这一步）。背景是低频平滑场，代价应该只是
# 一点点量化误差。这条测试把「等价」钉住 —— 如果哪天核尺寸换算写错，这里会红。
import numpy as np            # noqa: E402


def reference_norm(gray):
    """原分辨率版本，只用于对照。"""
    h, w = gray.shape
    k = max(15, (min(h, w) // 20) | 1)
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 4.0)
    bg[bg == 0] = 1
    return cv2.divide(gray, bg, scale=255)


tmp = _fixtures.TMP
worst_p99, worst_max = 0, 0
for f in CLEAN:
    p = _fixtures.photo_sim(os.path.join(FIX, f), os.path.join(tmp, 're_' + f), seed=5)
    g = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2GRAY)
    d = np.abs(omr._lighting_normalize(g).astype(int) - reference_norm(g).astype(int))
    worst_p99 = max(worst_p99, int(np.percentile(d, 99)))
    worst_max = max(worst_max, int(d.max()))
ok(worst_p99 <= 8, f'与全分辨率背景场基本一致（P99 差异 {worst_p99}/255 ≤ 8）')
ok(worst_max <= 16, f'最坏像素差异可忽略（{worst_max}/255）')

# 小图不该走降采样分支（核会相对变大，语义就变了）—— 尺寸守卫生效即可
small = np.full((40, 40), 200, np.uint8)
small[10:14, 10:14] = 30
ok(omr._lighting_normalize(small).shape == (40, 40), '小图（40×40）能正常处理不报错')
ok(omr._lighting_normalize(np.full((80, 60), 255, np.uint8)).min() >= 254,
   '纯白小图归一化后仍是白的（没有除零或饱和）')

print('\n' + ('🎉 阅卷核心全部通过' if fails == 0 else f'⚠️ {fails} 项未通过'))
sys.exit(0 if fails == 0 else 1)
