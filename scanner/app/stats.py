# 结果汇总：每题选项分布、正确率、个人得分
import csv
import io
from collections import Counter, defaultdict

FLAG_TEXT = {'ok': '', 'multi': '多选/存疑', 'faint': '浅涂存疑', 'blank': '未填'}


def parse_key(text):
    """解析标准答案：支持 `1A 2B 3C`、`1-A`、`A,B,C`（按题号顺序）等写法"""
    if not text:
        return {}
    t = text.strip()
    key = {}
    # 形如 "1A 2B" / "1-A" / "1=A" / "1:A"（分隔符可省略）
    pairs = []
    import re
    for m in re.finditer(r'(\d+)\s*[-=:：]?\s*([A-Za-z]+)', t):
        pairs.append((int(m.group(1)), m.group(2).upper()))
    if pairs:
        for no, v in pairs:
            key[no] = v
        return key
    # 只有字母序列：按题号顺序填入
    toks = [x.upper() for x in re.split(r'[\s,，;；]+', t) if x]
    if toks and all(len(x) <= 2 for x in toks):
        return {i + 1: v for i, v in enumerate(toks)}
    return {}


def summarize(sheets, question_numbers, key=None):
    """sheets: [{'name':..., 'answers': {no: {'answer','flag'}}}]"""
    qnos = sorted(question_numbers or {q for s in sheets for q in s['answers']})
    dist = {q: Counter() for q in qnos}
    n_blank = defaultdict(int)
    n_multi = defaultdict(int)
    n_correct = defaultdict(int)
    n_keyed = defaultdict(int)

    per_sheet = []
    for s in sheets:
        ans = s.get('answers', {})
        correct = 0
        wrong = []
        for q in qnos:
            a = ans.get(q, {})
            v, flag = a.get('answer'), a.get('flag')
            if v:
                dist[q][v] += 1
            if flag == 'blank':
                n_blank[q] += 1
            if flag in ('multi', 'faint'):
                n_multi[q] += 1
            kv = (key or {}).get(q)
            if kv:
                n_keyed[q] += 1
                if v and v == kv:
                    n_correct[q] += 1
                    correct += 1
                elif v:
                    wrong.append({'no': q, 'chose': v, 'key': kv})
        per_sheet.append({
            'name': s.get('name', ''),
            'score': correct,
            'total': len([q for q in qnos if (key or {}).get(q)]),
            'blank': len([q for q in qnos if ans.get(q, {}).get('flag') == 'blank']),
            'doubt': len([q for q in qnos if ans.get(q, {}).get('flag') in ('multi', 'faint')]),
            'wrong': sorted(wrong, key=lambda x: x['no']),
        })

    questions = []
    for q in qnos:
        total = sum(dist[q].values())
        row = {
            'no': q,
            'key': (key or {}).get(q, ''),
            'dist': {k: dist[q][k] for k in sorted(dist[q])},
            'blank': n_blank[q],
            'doubt': n_multi[q],
            'answered': total,
        }
        if key and key.get(q):
            row['correct'] = n_correct[q]
            row['rate'] = round(n_correct[q] / total * 100, 1) if total else 0.0
        questions.append(row)

    return {'questions': questions, 'sheets': per_sheet,
            'hasKey': bool(key), 'sheetCount': len(sheets)}


def score(answers, question_numbers, key):
    """按标准答案给一份卷子判分。

    必须先确认标准答案存在（`key.get(q)` 为真）再比对 —— 否则「学生未作答(None)」
    会与「标准答案里没有这一题(None)」相等，白送一分。
    """
    return sum(1 for q in question_numbers
               if key.get(q) and answers.get(q, {}).get('answer') == key.get(q))


def score_grading(answers, question_numbers, key, grading):
    """把人工复核叠加到自动判分之上，返回四元组：

      (correct_map, effective, total, final)

    - correct_map: {题号: True/False/None}，None 表示该题无标准答案、不参与判分。
    - effective: 逐题按「有复核用复核、没复核用自动」折算出来的对题数。
    - total: 有标准答案的题数。
    - final: 复核分。grading.manualScore 给了数字就直接用（覆盖逐题折算），否则等于 effective。

    题号键可能是字符串（JSON 读回来）也可能是 int（内存里），这里统一归一化成 int 再比对。
    """
    grading = grading or {}
    ov = {}
    for k, v in (grading.get('overrides') or {}).items():
        try:
            ov[int(k)] = bool(v)
        except (TypeError, ValueError):
            pass
    correct, eff, total = {}, 0, 0
    for q in question_numbers:
        kv = (key or {}).get(q)
        if not kv:
            correct[q] = None
            continue
        total += 1
        c = ov[q] if q in ov else (answers.get(q, {}).get('answer') == kv)
        correct[q] = c
        if c:
            eff += 1
    ms = grading.get('manualScore')
    final = ms if isinstance(ms, (int, float)) and not isinstance(ms, bool) else eff
    return correct, eff, total, final


def to_csv(rows, header):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
