# 自动评分规则引擎的测试：单选 / 多选漏选半对 / 七选三阶梯 / 倒扣 / 选择集推导。
# 纯逻辑测试，不碰 Flask 和数据库 —— python tests/test_scoring.py 直接跑。
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import scoring as sc   # noqa: E402

FAILS = []
def ok(c, m, extra=''):
    print(('  ✅ ' if c else '  ❌ ') + m + (f'  [{extra}]' if extra else ''))
    if not c:
        FAILS.append(m)

def eq(got, want, m, extra=''):
    ok(got == want, m + f'（期望 {want!r}，实测 {got!r}）', extra)

print('=== A. 选择集推导（inks → 学生涂了哪几个）===')
# 真实识别数据：D 实涂 0.827，印刷字母 0.15~0.25
eq(sc.selected_from_inks({'A': 0.192, 'B': 0.227, 'C': 0.163, 'D': 0.827}), 'D', '单涂 D → 只有 D')
# 七选三：涂了 A B D（C 没涂）
eq(sc.selected_from_inks({'A': 0.9, 'B': 0.8, 'C': 0.2, 'D': 0.85, 'E': 0.18, 'F': 0.16, 'G': 0.19}), 'ABD', '涂 ABD → ABD')
# 全没涂：印刷字母墨迹都接近 → 空
eq(sc.selected_from_inks({'A': 0.19, 'B': 0.2, 'C': 0.18, 'D': 0.21}), '', '全空 → 空集')
# 浅涂 0.38 vs 印刷 0.2 → 仍能识别（0.38-0.2=0.18≥0.15 但 0.38<0.5 → 不算）
eq(sc.selected_from_inks({'A': 0.38, 'B': 0.2, 'C': 0.18, 'D': 0.19}), '', '浅涂 0.38 低于 fill_min=0.5 → 不算（保守）')
# 空/坏数据
eq(sc.selected_from_inks(None), '', 'inks=None → 空')
eq(sc.selected_from_inks({}), '', 'inks={} → 空')

print('=== B. single 规则 ===')
r = sc.normalize_rule({'type': 'single', 'key': 'D', 'points': 2})
eq(sc.score_one(r, 'D')[0], 2.0, '答对得 2 分')
eq(sc.score_one(r, 'A')[0], 0.0, '答错 0 分')
eq(sc.score_one(r, '')[0], 0.0, '未答 0 分')
# 倒扣
r2 = sc.normalize_rule({'type': 'single', 'key': 'D', 'points': 2, 'wrong_penalty': 0.5})
eq(sc.score_one(r2, 'A')[0], -0.5, '答错倒扣 0.5')
eq(sc.score_one(r2, '')[0], 0.0, '未答不倒扣（未答≠答错）')

print('=== C. multi_partial（漏选得一半）===')
mp = sc.normalize_rule({'type': 'multi_partial', 'key': 'AB', 'points': 2, 'partial': 0.5})
eq(sc.score_one(mp, 'AB')[0], 2.0, '全对 2 分')
eq(sc.score_one(mp, 'A')[0], 1.0, '漏选（只涂 A）得一半 1 分')
eq(sc.score_one(mp, 'B')[0], 1.0, '漏选（只涂 B）得一半 1 分')
eq(sc.score_one(mp, 'AC')[0], 0.0, '错选（AC）0 分')
eq(sc.score_one(mp, '')[0], 0.0, '未答 0 分')
# 自定义比例 1/3
mp2 = sc.normalize_rule({'type': 'multi_partial', 'key': 'AB', 'points': 3, 'partial': 1/3})
eq(round(sc.score_one(mp2, 'A')[0], 4), round(1.0, 4), 'partial=1/3、满分 3 → 漏选 1 分')

print('=== D. pick_k（七选三阶梯 1/2/4）===')
k3 = sc.normalize_rule({'type': 'pick_k', 'key': 'ABC', 'points': 4,
                        'ladder': {0: 0, 1: 1, 2: 2, 3: 4}})
eq(sc.score_one(k3, 'ABC')[0], 4.0, '选对 3 个 → 4 分')
eq(sc.score_one(k3, 'AB')[0], 2.0, '选对 2 个 → 2 分')
eq(sc.score_one(k3, 'A')[0], 1.0, '选对 1 个 → 1 分')
eq(sc.score_one(k3, '')[0], 0.0, '全没涂 → 0 分')
# 选错一个：默认不倒扣，仍按正确数给阶梯
eq(sc.score_one(k3, 'ABD')[0], 2.0, '对2错1（不倒扣）→ 2 分')
eq(sc.score_one(k3, 'DEF')[0], 0.0, '全错 → 0 分')
# 选错倒扣
k3p = sc.normalize_rule({'type': 'pick_k', 'key': 'ABC', 'points': 4,
                         'ladder': {0: 0, 1: 1, 2: 2, 3: 4},
                         'penalty_wrong': True, 'wrong_penalty': 1})
eq(sc.score_one(k3p, 'ABD')[0], 1.0, '对2错1（每个错倒扣1）→ 2-1=1 分')
eq(sc.score_one(k3p, 'CDE')[0], 0.0, '对1错2 → 1-2=-1 → 保底 0 分')

print('=== E. apply_rules 端到端（含传统兼容与人工复核）===')
KEY = {1: 'D', 2: 'AB', 3: 'C'}
RULES = {'1': {'type': 'single', 'key': 'D', 'points': 2},
         '2': {'type': 'multi_partial', 'key': 'AB', 'points': 2, 'partial': 0.5}}
# 学生：1 对(D)、2 漏选(A)、3 对(C)
ANS = {1: {'answer': 'D', 'flag': 'ok', 'inks': {'A': .2, 'B': .19, 'C': .18, 'D': .8}},
       2: {'answer': 'A', 'flag': 'multi', 'inks': {'A': .8, 'B': .21, 'C': .19, 'D': .18}},
       3: {'answer': 'C', 'flag': 'ok', 'inks': {'A': .19, 'B': .2, 'C': .75, 'D': .18}}}
per, total, auto, final = sc.apply_rules(ANS, [1, 2, 3], KEY, RULES, {})
eq(total, 3, '参与计分 3 题')
eq(auto, 2 + 1 + 1, '自动总分 = 2(第1题) + 1(漏选半) + 1(第3题) = 4')
eq(final, 4.0, '无复核时 final = auto')
eq(per[2]['verdict'], '漏选', '第 2 题判「漏选」')
# 人工复核：第 2 题强制判对 → 漏选 1 分变满分 2
per2, _, _, final2 = sc.apply_rules(ANS, [1, 2, 3], KEY, RULES,
                                    {'overrides': {2: True}})
eq(final2, 5.0, '第 2 题判对后 2+2+1=5')
# manualScore 覆盖
_, _, _, final3 = sc.apply_rules(ANS, [1, 2, 3], KEY, RULES, {'manualScore': 7})
eq(final3, 7.0, 'manualScore=7 直接覆盖')
# 传统兼容：无规则时 answer==key 每题 1 分（不读 inks —— 老数据没有 inks 也要能判）
ANS_OLD = {1: {'answer': 'D', 'flag': 'ok'}, 2: {'answer': 'AB', 'flag': 'multi'},
           3: {'answer': 'X', 'flag': 'ok'}}
per4, total4, auto4, final4 = sc.apply_rules(ANS_OLD, [1, 2, 3], KEY, {}, {})
eq((total4, auto4, final4), (3, 2, 2.0), '无规则=传统判分：答对 key 的题各 1 分（D、AB 对，X 错）')

print('=== F. 规则归一化（宽松输入与非法丢弃）===')
r = sc.normalize_rule({'type': 'pick_k', 'key': 'a,b,c', 'points': '4', 'ladder': [0, 1, 2, 4]})
eq(r['key'], 'ABC', 'key 里的逗号空格被清掉并大写')
eq(r['points'], 4.0, 'points 字符串数字转 float')
eq(r['ladder'], {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0}, 'list 形式的 ladder 转成 {下标: 分}')
eq(sc.normalize_rule({'type': 'unknown'}), None, '未知类型丢弃')
eq(sc.normalize_rule('x'), None, '非字典丢弃')
eq(sc.normalize_rule(None), None, 'None 丢弃')

print()
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f in FAILS:
        print('   -', f)
    sys.exit(1)
print('🎉 评分规则引擎全部通过')
