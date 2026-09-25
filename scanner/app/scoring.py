# 自动评分规则引擎 —— 支持单选 / 多选漏选半对 / 七选三等自定义计分。
#
# 背景：识别层每题只存了「最佳选项」answer + 每题各选项的墨迹均值 inks。
# 多选（如七选三）要按「选了哪几个」计分，就得从 inks 反推学生实际涂了哪些选项。
# 规则引擎负责两件事：
#   1) 从 inks 推导学生的「选项选择集」selected（相对基线 + 绝对下限，跟 omr.decide 同一套判断）。
#   2) 按规则类型给 selected 与标准答案计分。

import re


# ---------------------------------------------------------------- 规则结构
#
# rules 存为 exam 的 JSON 列：{ 题号(str): rule }
# rule 字段（均可选，缺省取默认）：
#   type        'single'|'pick_k'|'multi_partial'
#   key         标准答案（大写字母串，多选用集合）。single 时也可用，取首字母。
#   points      满分（default 1）
#   wrong_penalty   选错时倒扣的分（default 0）
#   partial     漏选时拿满分的比例（multi_partial，default 0.5）
#   ladder      阶梯表 {正确个数: 得分}（pick_k，七选三典型 {0:0,1:1,2:2,3:4}）
#   penalty_wrong   pick_k 选错一个时是否按 wrong_penalty 倒扣（default false：选错仍按正确数给阶梯分）
#   fill_min    判定"涂了"的墨迹绝对下限（default 0.5）
#   rel_min     判定"涂了"的相对基线增量（default 0.15）

DEFAULT_POINTS = 1
DEFAULT_PARTIAL = 0.5
DEFAULT_LADDER = {0: 0, 1: 1, 2: 2}   # pick_k 无阶梯表时的兜底
FILL_MIN = 0.5
REL_MIN = 0.15

RULE_TYPES = ('single', 'pick_k', 'multi_partial')
RULE_TYPE_ZH = {
    'single': '单选/判断',
    'pick_k': '多选N项(七选三等)',
    'multi_partial': '多选·漏选得半',
}


def normalize_rule(r):
    """把用户可能给出的宽松写法规整成内部结构（只认合法字段，非法丢弃）。"""
    if not isinstance(r, dict):
        return None
    typ = r.get('type')
    if typ not in RULE_TYPES:
        return None
    out = {'type': typ}
    out['key'] = _norm_key(r.get('key'))
    try:
        out['points'] = float(r.get('points', DEFAULT_POINTS))
    except (TypeError, ValueError):
        out['points'] = DEFAULT_POINTS
    try:
        out['wrong_penalty'] = float(r.get('wrong_penalty', 0) or 0)
    except (TypeError, ValueError):
        out['wrong_penalty'] = 0.0
    try:
        out['partial'] = float(r.get('partial', DEFAULT_PARTIAL))
    except (TypeError, ValueError):
        out['partial'] = DEFAULT_PARTIAL
    out['penalty_wrong'] = bool(r.get('penalty_wrong'))
    # ladder：可能传 {正确数: 分}，也可能传 [分,分,分,...]（下标=正确数）
    lad = r.get('ladder')
    if isinstance(lad, dict):
        out['ladder'] = {int(k): float(v) for k, v in lad.items() if _isnum(k) and _isnum(v)}
    elif isinstance(lad, (list, tuple)):
        out['ladder'] = {i: float(v) for i, v in enumerate(lad) if _isnum(v)}
    else:
        out['ladder'] = dict(DEFAULT_LADDER)
    if not out['ladder']:
        out['ladder'] = dict(DEFAULT_LADDER)
    try:
        out['fill_min'] = float(r.get('fill_min', FILL_MIN))
    except (TypeError, ValueError):
        out['fill_min'] = FILL_MIN
    try:
        out['rel_min'] = float(r.get('rel_min', REL_MIN))
    except (TypeError, ValueError):
        out['rel_min'] = REL_MIN
    return out


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _norm_key(k):
    if isinstance(k, str):
        return re.sub(r'[^A-Za-z]', '', k).upper()
    if isinstance(k, (list, tuple)):
        return ''.join(str(x).upper() for x in k if str(x).isalpha())
    return ''


# ---------------------------------------------------------------- 选项选择集推导

def selected_from_inks(inks, fill_min=FILL_MIN, rel_min=REL_MIN):
    """从每题各选项墨迹均值反推学生涂了哪几个选项。

    跟 omr.decide 同一套判断：墨迹相对该题最浅选项的增量够大、且绝对值不低，
    就认为是「涂了」。印刷字母本身的墨迹约 0.15~0.25，浅涂约 0.38，实涂 >0.5。
    返回按字母排序的选中集合（大写字母串）。
    """
    if not inks or not isinstance(inks, dict):
        return ''
    vals = [v for v in inks.values() if isinstance(v, (int, float))]
    if not vals:
        return ''
    base = min(vals)
    sel = [opt for opt, ink in inks.items()
           if isinstance(ink, (int, float)) and ink - base >= rel_min and ink >= fill_min]
    return ''.join(sorted(x.upper() for x in sel))


# ---------------------------------------------------------------- 计分

def _set(s):
    return set(x.upper() for x in (s or '') if x.isalpha())


def score_one(rule, selected, key=None):
    """按规则给「一题」计分。

    rule    normalize_rule 之后的规则（None → 当 single，1 分）。
    selected   学生选项选择集（大写字母串，如 'ABC'）。空串 = 未作答。
    key    该题标准答案（大写字母串）。规则里没有 key 时用它。

    返回 (得分, 明细)。明细用于成绩单逐题展示。
    """
    rule = rule or {'type': 'single', 'points': DEFAULT_POINTS, 'wrong_penalty': 0.0,
                    'partial': DEFAULT_PARTIAL, 'penalty_wrong': False,
                    'ladder': dict(DEFAULT_LADDER), 'fill_min': FILL_MIN, 'rel_min': REL_MIN}
    rkey = _set(rule.get('key') or key or '')
    s = _set(selected)
    points = float(rule.get('points', DEFAULT_POINTS))
    typ = rule.get('type', 'single')

    if typ == 'single':
        # 单选：全对得 points；答错 0 或倒扣；未答 0（没作答不该被罚）。
        if s == rkey and rkey:
            return points, {'verdict': '对', 'score': points}
        if not s:
            return 0.0, {'verdict': '未答', 'score': 0.0}
        return -float(rule.get('wrong_penalty', 0)), {'verdict': '错',
                                                      'score': -float(rule.get('wrong_penalty', 0))}

    if typ == 'multi_partial':
        # 多选漏选半对：全对=points；漏选（所选都是对的但没选全）= points*partial；错选=0或倒扣。
        if not s:
            return -float(rule.get('wrong_penalty', 0)), {'verdict': '未答',
                                                          'score': -float(rule.get('wrong_penalty', 0))}
        if s == rkey:
            return points, {'verdict': '全对', 'score': points}
        if s.issubset(rkey) and rkey:
            half = points * float(rule.get('partial', DEFAULT_PARTIAL))
            return half, {'verdict': '漏选', 'score': half}
        return -float(rule.get('wrong_penalty', 0)), {'verdict': '错选',
                                                      'score': -float(rule.get('wrong_penalty', 0))}

    # pick_k：按「选对几个」查阶梯给分。典型七选三 {0:0,1:1,2:2,3:4}。
    ladder = {int(k): float(v) for k, v in rule.get('ladder', {}).items()}
    n_correct = len(s & rkey) if rkey else 0
    n_wrong = len(s - rkey)
    base_score = ladder.get(n_correct, 0.0)
    if n_wrong and rule.get('penalty_wrong'):
        base_score -= float(rule.get('wrong_penalty', 0)) * n_wrong
    if base_score < 0:
        base_score = 0.0
    if not s:
        base_score = 0.0
    verdict = f'对{n_correct}/错{n_wrong}'
    return base_score, {'verdict': verdict, 'score': base_score,
                        'correct': n_correct, 'wrong': n_wrong}


def apply_rules(answers, qnos, key, rules=None, grading=None):
    """把规则+人工复核叠加到一份卷子上，返回：
      (per_q, total, auto_total, final)
    per_q:   {题号: {'auto': 自动对错(bool/None), 'score': 复核后得分, 'verdict': 文本,
                    'correct': 该题是否判对(bool), 'selected': 学生选择集, 'key': 标准答案}}
    total:   有标准答案、参与计分的题数
    auto_total: 纯自动（规则）总得分
    final:   复核总得分（grading.manualScore 给了数字则覆盖，否则 = Σ per_q.score 且用规则）
    """
    rules = rules or {}
    grading = grading or {}
    ov = {}
    for k, v in (grading.get('overrides') or {}).items():
        try:
            ov[int(k)] = bool(v)
        except (TypeError, ValueError):
            pass
    ms = grading.get('manualScore')

    per_q = {}
    auto_total, final_total, total = 0.0, 0.0, 0
    for q in qnos:
        kv = (key or {}).get(q)
        qkey = kv
        ans = (answers or {}).get(q) or {}
        # 只有显式配了规则才走规则计分；没配 → 保持传统"单选项精确匹配，每题 1 分"。
        rule = normalize_rule(rules.get(str(q), rules.get(q))) if rules else None

        if rule is None:
            # 传统判分：answer == key 才算对（空标准答案不参与）。
            if not kv:
                per_q[q] = {'auto': None, 'score': 0.0, 'verdict': '无标准答案',
                            'correct': None, 'selected': str(ans.get('answer') or '').upper(),
                            'key': ''}
                continue
            total += 1
            auto_correct = (ans.get('answer') or '') == kv
            auto_score = 1.0 if auto_correct else 0.0
            auto_total += auto_score
            if q in ov:
                eff_score = (1.0 if ov[q] else 0.0)
                eff_verdict = '判对' if ov[q] else '判错'
            else:
                eff_score = auto_score
                eff_verdict = '对' if auto_correct else '错'
            final_total += eff_score
            per_q[q] = {
                'auto': auto_correct,
                'score': eff_score,
                'verdict': eff_verdict,
                'correct': eff_score > 0,
                'selected': str(ans.get('answer') or '').upper(),
                'key': qkey or '',
            }
            continue

        # 有显式规则：从 inks 推导学生涂了哪几个选项再计分。
        total += 1
        selected = selected_from_inks(ans.get('inks'), rule.get('fill_min', FILL_MIN),
                                      rule.get('rel_min', REL_MIN))
        if not selected and ans.get('answer'):
            # inks 缺失（老数据/手工补录）时，退回到识别的单选项。
            selected = str(ans['answer']).upper()
        # 纯自动分：只看规则，不看人工 override。
        auto_score, auto_det = score_one(rule, selected, qkey)
        auto_total += auto_score
        # 复核后分：override 单题强制对/错，覆盖自动判定。
        if q in ov:
            eff_score = (float(rule.get('points', DEFAULT_POINTS)) if ov[q] else 0.0)
            eff_verdict = '判对' if ov[q] else '判错'
        else:
            eff_score = auto_score
            eff_verdict = auto_det.get('verdict', '')
        final_total += eff_score
        per_q[q] = {
            'auto': auto_score > 0,
            'score': eff_score,
            'verdict': eff_verdict,
            'correct': eff_score > 0,
            'selected': selected or (ans.get('answer') or ''),
            'key': qkey or '',
        }
    if ms is not None and not isinstance(ms, bool):
        try:
            final = float(ms)
        except (TypeError, ValueError):
            final = final_total
    else:
        final = final_total
    return per_q, total, auto_total, final