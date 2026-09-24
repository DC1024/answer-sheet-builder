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
    """跑一组素材，返回 (答案平均正确率, {文件: (第3题flag, 第8题flag)}, 考号直读正确率)"""
    accs, flags, sid_hit = [], {}, []
    for f in sorted(files):
        # 手机图在临时目录（绝对路径），取 basename 才能对上 expected.json 的 s01/s02…
        key = os.path.splitext(os.path.basename(f))[0].replace('_phone', '')
        exp = STUDENTS[key]['answers']
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
        # 考号从卷面直读（不再依赖文件名）—— 读错一位就是把卷子归错人，必须逐份核
        sid_hit.append(bool(r['sid']) and r['sid']['text'] == STUDENTS[key]['sid'])
        # 存疑标记：每个学生的第 3（未涂）/ 8（浅涂）/ 15（涂两个）题各一处
        flags[os.path.basename(f)] = {no: flg.get(no) for no in QEDGE}
    acc = sum(accs) / len(accs)
    sid_acc = sum(sid_hit) / len(sid_hit)
    print(f'  {name}: 答案 {acc * 100:.1f}%（{len(accs)} 份）/ 考号 {sid_acc * 100:.1f}%')
    return acc, flags, sid_acc


def flag_misses(flags, want=None):
    """返回 {文件: {题号: (期望, 实测)}}，只列出不符的（want 默认取 expected.json 的 questionEdges）"""
    want = QEDGE if want is None else want
    return {f: {no: (want[no], v.get(no)) for no in want if v.get(no) != want[no]}
            for f, v in flags.items() if any(v.get(no) != want[no] for no in want)}


def _load_overlay(r):
    import numpy as np
    return cv2.imdecode(np.frombuffer(r['overlayPng'], np.uint8), cv2.IMREAD_COLOR)


TPL = omr.load_template(open(os.path.join(FIX, 'template.json'), encoding='utf-8').read())
EXPECTED = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))
STUDENTS = EXPECTED['students']        # {s01: {sid, answers}}
SID_EDGES = EXPECTED['sidEdges']       # {x1-blank: {sid, pos, variant, flag, text, ...}}
QEDGE = {int(k): v for k, v in EXPECTED['questionEdges'].items()}   # {3: blank, 8: faint, 15: multi}
CLEAN = sorted(f for f in os.listdir(FIX) if f.startswith('s') and f.endswith('.png'))
EDGE = sorted(f for f in os.listdir(FIX) if f.startswith('x') and f.endswith('.png'))

_fix_keys = {os.path.splitext(f)[0] for f in CLEAN}
_edge_keys = {os.path.splitext(f)[0] for f in EDGE}
ok(set(STUDENTS) == _fix_keys,
   f'expected.json 的学生与 s*.png 一一对应（差集 {sorted(set(STUDENTS) ^ _fix_keys) or "空"}）')
ok(set(SID_EDGES) == _edge_keys,
   f'expected.json 的边界素材与 x*.png 一一对应（差集 {sorted(set(SID_EDGES) ^ _edge_keys) or "空"}）')

print('=== A. 干净扫描（300dpi 级） ===')
acc_clean, flags_clean, sid_clean = run_case(TPL, CLEAN, '干净扫描')
ok(acc_clean >= 0.99, f'干净扫描准确率 {acc_clean * 100:.1f}% ≥ 99%')
ok(sid_clean >= 0.99, f'考号从卷面直读 {sid_clean * 100:.1f}% ≥ 99%（不依赖文件名）')
_bad = flag_misses(flags_clean)
ok(not _bad, f'每份卷的三处存疑都判对（未涂 blank / 浅涂 faint / 涂两个 multi）{_bad or ""}')

print('\n=== B. 手机拍照模拟（透视+明暗+模糊+噪声+JPEG） ===')
PHONE = [p for _, p in _fixtures.phone_variants(CLEAN)]
acc_phone, flags_phone, sid_phone = run_case(TPL, PHONE, '手机拍照模拟')
ok(acc_phone >= 0.95, f'拍照模拟准确率 {acc_phone * 100:.1f}% ≥ 95%')
ok(sid_phone >= 0.95, f'拍照图里考号仍读得对 {sid_phone * 100:.1f}% ≥ 95%')
# 拍照之后 flag 具体落成 faint 还是 multi 可以变（噪声就叠在那儿），但**绝不能变成 ok** ——
# 把存疑当正常作答，是这套系统唯一会静默出错的路径。
_wrong = {f: {no: v[no] for no in QEDGE if v[no] == 'ok'}
          for f, v in flags_phone.items() if any(v[no] == 'ok' for no in QEDGE)}
ok(not _wrong, f'拍照图里三处存疑没有一处被当成正常作答（实测 {_wrong or "全对"}）')
ok(flags_phone[os.path.basename(PHONE[0])][8] == 'faint', '拍照图里第 8 题（浅涂）仍标为 faint')

print('\n=== C. 阈值容错：把填涂阈值调低后拍照图仍稳 ===')
acc_low, _, sid_low = run_case(TPL, PHONE, '低阈值拍照', fill_min=0.4, gap=0.12)
ok(acc_low >= 0.95, f'低阈值拍照准确率 {acc_low * 100:.1f}% ≥ 95%')
ok(sid_low >= 0.95, f'低阈值下考号仍读得对 {sid_low * 100:.1f}% ≥ 95%')

print('\n=== D. 考号边界：漏涂 / 浅涂 / 一列涂两个 ===')
# 考号是「这份卷子归到谁名下」的唯一依据，读错一位就等于把卷子归给别人。
# 素材库只有这三种情况能证明「读不准的时候它会说自己读不准」——
# 识别不出来不可怕，**读错了却报 ok** 才可怕，所以这里逐位断言 flag。
for ef in EDGE:
    name = os.path.splitext(ef)[0]
    want = SID_EDGES[name]
    r = omr.recognize(cv2.imread(os.path.join(FIX, ef)), TPL, px_per_mm=8.0)
    s = r.get('sid')
    if not s:
        ok(False, f'{name}：模板里有考号填涂区，却没解出考号')
        continue
    pos = next((p for p in s['positions'] if p['pos'] == want['pos']), None)
    if pos is None:
        ok(False, f'{name}：返回的逐位明细里没有第 {want["pos"]} 位')
        continue
    ok(pos['flag'] == want['flag'],
       f'{name}（{want["why"]}）第 {want["pos"]} 位判为 {want["flag"]}'
       f'（实测 {pos["flag"]}，ink={pos["ink"]}）')
    ok(s['ok'] is False, f'{name}：整体 is-ok 为 False（不会冒充「读得干净」）')
    if 'text' in want:
        ok(s['text'] == want['text'], f'{name}：读出 {s["text"]}（期望 {want["text"]}，? = 这一位没读出来）')
    if 'digit' in want:
        ok(pos['digit'] == want['digit'], f'{name}：第 {want["pos"]} 位数字 {pos["digit"]}（期望 {want["digit"]}）')
    if 'digitAny' in want:
        ok(pos['digit'] in want['digitAny'],
           f'{name}：选中 {pos["digit"]}，落在候选 {want["digitAny"]} 里'
           f'（两格一样深 0.827，选哪个都对，但必须报 doubt）')
    if want['flag'] == 'blank':
        ok(s['filled'] == s['digits'] - 1, f'{name}：只有 {s["filled"]}/{s["digits"]} 位读到数字')

# 老模板（asb-omr/1，没有考号区）必须继续能用，只是拿不到卷面考号
_v1 = json.loads(json.dumps(TPL))
for p in _v1['pages']:
    p.pop('sid', None)
_v1['format'] = 'asb-omr/1'
_v1.pop('sid', None)
_v1t = omr.load_template(_v1)
ok(omr.template_summary(_v1t)['sid'] is None, 'asb-omr/1 老模板：摘要里明确报告「没有考号区」')
r_v1 = omr.recognize(cv2.imread(os.path.join(FIX, CLEAN[0])), _v1t, px_per_mm=8.0)
ok(r_v1.get('sid') is None, 'asb-omr/1 老模板：认不出考号时返回 None（不报错、不影响选择题）')
v1_flags = {q['no']: q['flag'] for q in r_v1['questions']}
ok(v1_flags == {**{no: 'ok' for no in range(1, 21)}, **QEDGE},
   f'asb-omr/1 老模板：20 题判定与 v2 完全一致（存疑 {sum(1 for f in v1_flags.values() if f != "ok")} 处）')

print('\n=== E. 汇总统计与判分 ===')
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

print('\n=== F. 光照归一化：降采样背景与原分辨率等价 ===')
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
