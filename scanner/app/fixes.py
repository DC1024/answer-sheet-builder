# -*- coding: utf-8 -*-
"""人工修正：老师改掉机器读错的答案，并据此统计**各识别方案的误判率**。

------------------------------------------------------------------
两件事必须分清（界面和代码里都别再混）
------------------------------------------------------------------
  fixes       改的是**答案本身**（机器读成 C，其实是 B）→ 影响分布统计、导出、判分
  grading.overrides  改的是**判分结论**（这题判对/判错）→ 只影响分数

举例：学生涂了 B，机器读成 C —— 这属于机器识别错误，该用 fixes 改成 B，
分布统计和「机器误判率」都会跟着对。
另一种情况：学生涂了 B，机器也读成 B，但老师认为题干有争议想给分 ——
这不关识别的事，该用 overrides 判对。用 fixes 去改反而会把答案改错。

------------------------------------------------------------------
为什么要单独统计「按方案分的误判率」
------------------------------------------------------------------
老师要判断「结构特征规则」和「CNN」哪套更准。能用的信号只有一个：
**老师亲手改过的那些题**。于是：
    某方案的修正率 = 该方案定音的题里，被老师改掉的题数 / 该方案定音的题数

⚠️ 这是个**有偏样本**，必须说清楚，否则会被误读成准确率：
  1. 只有老师看过并动手改的题才进统计 —— 机器读对且老师没细看的题不在内，
     所以它衡量的是「**在被检查到的题里**出错的比例」，不是全量准确率。
  2. 老师本来就会优先去看机器标了 review/doubt 的题，这会让高置信方案
     看起来更准（它标得少、被检查得少）。
  3. 样本量小的时候（比如某个方案只定音了 3 题）数字没有意义。
所以这里回吐的字段名全部带 `reviewed`/`corrected` 字样，并在 summary 里
塞一句 `caveat`，让界面必须原样展示这句话。
"""
from datetime import datetime


class FixError(Exception):
    """修正数据不合法。信息直接给用户看。"""


# 修正后这一题的 flag 用什么值。
# 特意**不放进 stats.DOUBT_FLAGS** —— 人工已经确认过的题不该继续留在「待复核」里。
FLAG_FIXED = 'fixed'

MAX_ANSWER = 8          # 一道题的答案最多几个字符（多选如 ABCD 也够）

# 归桶：把逐题的 `by` 收成统计口径里的方案名。
#   rule / cnn / both —— 三种真实来源，原样保留
#   None 及其它       —— 'unknown'（老库的扫描结果没有 by；让它们自己占一行，
#                        宁可显示「无来源信息」也不要硬塞给某个方案去污染它的战绩）
_BUCKETS = ('rule', 'cnn', 'both')
_BUCKET_ZH = {'rule': '结构特征规则', 'cnn': 'CNN',
              'both': '两路均未定音', 'unknown': '无来源信息（老数据）'}
_SHOW = {None: '空', '': '空'}      # 机器读成空（未作答）时在混淆表里怎么显示


def _bucket(by):
    return by if by in _BUCKETS else 'unknown'


def _now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def normalize_entry(v, who=''):
    """把前端传来的一条修正收成规整形状。

    认两种写法：
      'B'                      —— 只给答案（最省事，前端默认走这种）
      {'answer': 'B', ...}     —— 带备注等附加信息
    返回 {'answer': 'B', 'note': '', 'by': who, 'at': <iso>}；不合法则抛 FixError。
    """
    if isinstance(v, str):
        ans, note = v, ''
    elif isinstance(v, dict):
        ans = v.get('answer')
        note = str(v.get('note') or '')[:200]
        # 允许客户端传 at/by，但以服务端为准（客户端的时钟不可信）
    else:
        raise FixError('修正内容必须是字母串或 {"answer": ...} 对象')

    ans = _clean_answer(ans)
    if ans is None:
        raise FixError('修正后的答案不合法（只接受 A-Z 字母，最多 %d 个）' % MAX_ANSWER)
    out = {'answer': ans, 'note': note, 'by': str(who or ''), 'at': _now()}
    return out


def _clean_answer(ans):
    """答案归一化：去空白、转大写、只留字母、限长。返回 None 表示不合法。"""
    if ans is None:
        return None
    s = ''.join(ch for ch in str(ans).strip().upper() if ch.isalpha())
    if not s or len(s) > MAX_ANSWER:
        return None
    return s


def normalize_all(raw, who=''):
    """整份修正表归一化。`raw` 形如 {"1": "B", "3": {"answer": "AC"}}。

    题号键统一转 int —— 跟 answers 同一条规矩（见 store.qno / _QKEYED），
    否则落库过一遍 JSON 就变成字符串键，跟内存里的 int 对不上，修正会**静默失效**。
    """
    if raw in (None, ''):
        return {}
    if not isinstance(raw, dict):
        raise FixError('修正表必须是对象：{"题号": "答案"}')
    out = {}
    for k, v in raw.items():
        no = _qno(k)
        if no is None:
            raise FixError(f'题号不合法：{k!r}')
        out[no] = normalize_entry(v, who)
    return out


def _qno(k):
    """题号归一化。跟 store.qno 同一套语义，但这里返回 None 表示日志里不认识的键。"""
    if isinstance(k, bool):
        return None
    if isinstance(k, int):
        return k
    try:
        return int(str(k).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def apply(answers, fixes):
    """机器答案 + 人工修正 → 生效答案（**不修改入参**）。

    返回 (merged, changed)：
      merged   生效答案 {题号: 条目}；被改过的条目上带
                 fixed=True / machine='C'（机器原读）/ machineFlag / fixNote / fixBy
      changed  实际发生变化的题号集合（老师把 B 改成 B 不算变化）

    为什么保留 machine / machineFlag 而不是直接覆盖掉：
    老师要看清「机器本来读成什么」才知道自己改了什么；而且**误判率统计**
    全靠这个「机器原读 vs 人工修正」的配对，覆盖掉就永远算不出来了。
    """
    out = {}
    changed = set()
    for q, a in (answers or {}).items():
        out[q] = dict(a or {})
    for q, f in (fixes or {}).items():
        entry = out.setdefault(q, {})
        machine = entry.get('answer')
        new = f.get('answer')
        if machine == new:
            # 老师在界面上点了但答案没变 —— 不记成一次修正（否则误判率会虚高）
            continue
        entry['machine'] = machine
        entry['machineFlag'] = entry.get('flag')
        entry['machineBy'] = entry.get('by')
        entry['answer'] = new
        entry['flag'] = FLAG_FIXED
        entry['by'] = 'fix'
        entry['fixNote'] = f.get('note') or ''
        entry['fixBy'] = f.get('by') or ''
        entry['fixAt'] = f.get('at') or ''
        out[q] = entry
        changed.add(q)
    return out, changed


def engine_accuracy(sheets, qnos=None):
    """按识别方案统计「被老师改掉」的比例。

    sheets: [{'answers': {题号: 条目}, 'fixes': {题号: {...}}, ...}] —— **必须是
            未经 apply() 合并的原始 answers**（条目里才留着 by 字段）。
    qnos:   参与统计的题号；不给就从数据里推。

    每条修正贡献一次「某方案定音的题被改掉」。返回结构见文件头说明。

    ⚠️ 注意单张扫描结果（exam_scans）历史上没有 by 字段 —— 老数据 by 全是 None，
    会被归到 `unknown` 桶而不是硬塞给某个方案。宁可显示「无来源信息」也不要编。
    """
    engines = {}          # {engine: {'decided': n, 'corrected': m}}
    fixes_total = 0
    decided_total = 0
    by_letter = {}        # {'<engine>:C->B': n} 供看「机器读成啥、老师改成啥」

    # 分子：老师改掉的题，按「改之前是谁定的音」归类
    for s in sheets or []:
        ans = (s or {}).get('answers') or {}
        fxs = (s or {}).get('fixes') or {}
        for q, f in fxs.items():
            if qnos and q not in qnos:
                continue
            a = ans.get(q) or {}
            machine = a.get('answer')
            new = (f or {}).get('answer')
            if machine == new:
                continue                  # 点了但没改，不算一次修正
            eng = _bucket(a.get('by'))
            engines.setdefault(eng, {'decided': 0, 'corrected': 0})['corrected'] += 1
            fixes_total += 1
            tag = _SHOW.get(machine) or machine or '空'
            by_letter[f'{eng}:{tag}->{new}'] = by_letter.get(f'{eng}:{tag}->{new}', 0) + 1

    # 分母：各方案**定音过的题总数**（逐题 by 计数，跨全部卷子）
    #
    # 注意这里把「没有 by」的题也算进 unknown 的分母，而不是跳过 —— 分子那边
    # 无来源的修正同样记在 unknown 名下，两边必须用同一套归桶规则。早先分母跳过
    # 无 by 的题、分子却照记，会产出「decided 0 / corrected 1」这种读不通的行
    # （老库的扫描结果没有 by，正好撞上这一条）。
    for s in sheets or []:
        ans = (s or {}).get('answers') or {}
        for q, a in ans.items():
            if qnos and q not in qnos:
                continue
            by = (a or {}).get('by')
            if by == 'fix':
                continue                  # 人工改过的不再算某个方案的战绩
            engines.setdefault(_bucket(by), {'decided': 0, 'corrected': 0})['decided'] += 1
            decided_total += 1

    rows = []
    for eng, slot in sorted(engines.items()):
        n, m = slot['decided'], slot['corrected']
        rows.append({
            'engine': eng,
            'engineZh': _BUCKET_ZH.get(eng, eng),
            'decided': n,              # 该方案定音过的题数（分母）
            'corrected': m,            # 其中被老师改掉的题数（分子）
            'rate': round(m / n * 100, 1) if n else None,
        })
    # 先按「改动数」降序 —— 改动多的方案最该被关注（它可能真的差，
    # 也可能只是它负责的题本身就难，所以同时给出 decided 让人自己判断）。
    rows.sort(key=lambda r: (-r['corrected'], r['engine']))
    unknown = next((r for r in rows if r['engine'] == 'unknown'), None)
    if unknown:
        # 无来源（老数据）那一行放在最下面 —— 老师大概率要比较的是 rule / cnn，
        # 把 unknown 顶上排序只会干扰「哪套更准」的判断。
        rows.remove(unknown)
        rows.append(unknown)

    return {
        'rows': rows,
        'corrected': fixes_total,
        'decided': decided_total,
        'rate': round(fixes_total / decided_total * 100, 1) if decided_total else None,
        'confusions': [{'key': k, 'count': v}
                       for k, v in sorted(by_letter.items(), key=lambda x: -x[1])][:40],
        # 这句话必须原样出现在界面上 —— 少一句就会被当成准确率用。
        'caveat': ('只统计「老师亲手改过的题」：机器读对且没人细看的题不在分母里，'
                   '所以这是「被检查到的题里的出错比例」，不等于全量准确率；'
                   '老师通常优先检查机器标了存疑的题，也会让高置信方案显得更准。'
                   '样本量小的时候不要下结论。'),
    }