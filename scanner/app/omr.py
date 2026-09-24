# 答题卡扫描识别核心：四角定位点透视矫正 + 阅卷模板坐标采样判定填涂。
# 全流程纯 OpenCV/NumPy，不下载任何模型，CPU 即可运行，可完全离线。
#
# 模板格式：
#   asb-omr/1  只有选择题填涂圈
#   asb-omr/2  另有考生信息栏的「考号填涂区」（pages[].sid）—— 卷面直读考号，不必往文件名写
import json
import math
import numpy as np
import cv2

FORMAT = 'asb-omr/2'
FORMAT_READABLE = ('asb-omr/1', 'asb-omr/2')

# 采样框相对填涂圈方框的收缩比例（避开印刷的方括号边框）
SHRINK = 0.60

# 考号每一位的判定：
#   一位数字填涂后 ink ≈ 0.8，而同列其余 9 格是空白的（底噪 0.15~0.25），
#   相对差非常明显；所以「填了但没涂实」用 faint、「一列涂了两个」用 doubt。
SID_REL_MIN = 0.15      # 与列内最浅的格子之差小于它就认为「这一位没涂」
SID_GAP = 0.12          # 最优与次优的差距小于它就认为「一列涂了两个 / 涂糊了」
SID_SECOND_MIN = 0.2    # 次优那一格自己也得够深才叫 doubt（同 decide 的 second_rel_min）


class OmrError(Exception):
    pass


def _qno(v):
    """题号尽量转 int；实在转不了就原样留着（别为一个怪题号让整份模板载不进来）。"""
    if isinstance(v, bool) or v is None:
        return v
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return v


def load_template(src):
    """src 可以是 JSON 字符串、bytes 或已解析的 dict。

    接受 asb-omr/1（只有选择题）与 asb-omr/2（另有考号填涂区）——
    老模板不必重新导出就能继续用，只是拿不到卷面考号。
    """
    tpl = json.loads(src) if isinstance(src, (str, bytes, bytearray)) else src
    if not isinstance(tpl, dict) or tpl.get('format') not in FORMAT_READABLE:
        raise OmrError(f'不是有效的阅卷模板（format 应为 {" 或 ".join(FORMAT_READABLE)}）')
    if not tpl.get('pages'):
        raise OmrError('模板里没有任何面（pages 为空）')
    # 题号在这里就统一成 int —— 它是整条链路的主键类型：
    # 模板的 q['no']、answers 的键、标准答案的键、stats 的 qnos 全是它。
    # 不统一的话，混着 int/str 的键会在两处静默出事：sorted() 直接 TypeError，
    # 以及落库过一遍 JSON 后 answers.get(1) 落空 → 全班 0 分（见 store._load_answers）。
    for p in tpl['pages']:
        for q in p.get('questions') or []:
            if isinstance(q, dict) and 'no' in q:
                q['no'] = _qno(q['no'])
    return tpl


def template_summary(tpl):
    pages = tpl.get('pages', [])
    sid_pages = [p.get('index', i) for i, p in enumerate(pages) if p.get('sid')]
    sid_digits = (tpl.get('sid') or {}).get('digits') or 0
    return {
        'format': tpl.get('format'),
        'paper': tpl.get('paper'),
        'marks': tpl.get('marks'),
        'pages': [{'index': p.get('index', i), 'questions': len(p.get('questions', []))}
                  for i, p in enumerate(pages)],
        'questionCount': tpl.get('questionCount') or sum(len(p.get('questions', [])) for p in pages),
        'questionNumbers': sorted({q['no'] for p in pages for q in p.get('questions', [])}),
        'sid': ({'digits': sid_digits, 'pages': sid_pages} if sid_pages else None),
    }


def _template_quad(tpl, page_idx=0):
    """模板中四个定位点在 mm 网格上的顺序点：tl, tr, br, bl"""
    pages = tpl['pages']
    idx = min(max(0, page_idx), len(pages) - 1)
    page = pages[idx]
    marks = {m.get('pos'): m for m in page.get('marks', [])}
    for pos in ('tl', 'tr', 'br', 'bl'):
        if pos not in marks:
            raise OmrError(f'模板第 {idx} 面缺少 {pos} 定位点，请重新导出阅卷模板')
    return np.float32([[marks[p]['x'], marks[p]['y']] for p in ('tl', 'tr', 'br', 'bl')]), idx


def _lighting_normalize(gray, down=4):
    """抑制手机拍照的明暗渐变：用形态学背景做除法归一化。

    背景是一层**低频平滑场**，没必要在原分辨率上估 —— 159×159 的椭圆闭运算在 14M 像素上
    要近 1 秒（容器里更慢），而整条识别里其它部分加起来才 100ms 出头。先按 1/4 降采样算出
    背景再插值回来，成本降到约 1/16，背景本身几乎不变。

    核尺寸按**原图**算、再换算到小图上（`k*scale`），保证物理邻域和原来一致 ——
    否则小图上的 `max(15, …)` 下限会让小图用上相对更大的核。
    """
    h, w = gray.shape
    scale = 1.0 / down if down > 1 and min(h, w) >= 4 * 64 else 1.0

    k = max(15, (min(h, w) // 20) | 1)                  # 原图上的核（保持原语义）
    work = gray
    if scale != 1.0:
        work = cv2.resize(gray, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                          interpolation=cv2.INTER_AREA)
    ks = max(3, int(round(k * scale)) | 1)
    bg = cv2.morphologyEx(work, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ks, ks)))
    bg = cv2.GaussianBlur(bg, (0, 0), ks / 4.0)
    if scale != 1.0:
        bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    bg[bg == 0] = 1
    return cv2.divide(gray, bg, scale=255)


def detect_marks(bgr, tpl, page_idx=0):
    """在扫描图里找四个定位点，返回 (图像坐标 quad, 诊断信息)"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    norm = _lighting_normalize(gray)

    pxmm = min(gray.shape[1] / float(tpl['paper']['w']), gray.shape[0] / float(tpl['paper']['h']))
    side = float(tpl.get('marks', {}).get('size') or 4.0) * pxmm      # 定位点边长（px，上限估计）
    exp_area = side * side
    # 三角形定位点实际面积约为方块的一半，所以下限放到 0.25
    lo, hi = exp_area * 0.25, exp_area * 2.2

    thr = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    h, w = thr.shape
    band_x, band_y = w * 0.22, h * 0.22     # 定位点一定落在页边内侧，不会跑到版心

    cnts, _ = cv2.findContours(thr, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cand = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < lo or a > hi:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if bw <= 0 or bh <= 0:
            continue
        ar = bw / float(bh)
        if ar < 0.55 or ar > 1.8:            # 近似方形（三角形裁切后仍是方形外框）
            continue
        if a / float(bw * bh) < 0.30:        # 实心度：方块≈1，三角≈0.5
            continue
        cx, cy = x + bw / 2.0, y + bh / 2.0
        if not (cx < band_x or cx > w - band_x or cy < band_y or cy > h - band_y):
            continue                          # 在版心区域 → 不是定位点
        cand.append((cx, cy, a))

    if len(cand) < 4:
        raise OmrError(f'只找到 {len(cand)} 个定位点候选（需要 4 个）：请确认扫描件完整、四角定位点清晰')

    tl = min(cand, key=lambda p: p[0] + p[1])
    br = max(cand, key=lambda p: p[0] + p[1])
    tr = max(cand, key=lambda p: p[0] - p[1])
    bl = min(cand, key=lambda p: p[0] - p[1])
    quad = np.float32([[tl[0], tl[1]], [tr[0], tr[1]], [br[0], br[1]], [bl[0], bl[1]]])

    # 形状自检：四个点应构成面积足够大的四边形（否则多半误检）
    area = cv2.contourArea(quad.reshape(4, 1, 2))
    if area < 0.35 * w * h:
        raise OmrError(f'定位点构成的四边形过小（{area / (w * h):.2f} 图幅），疑似误检 —— 请检查扫描件四角')

    diag = {'candidates': len(cand), 'pxPerMm': round(pxmm, 2), 'expectedSidePx': round(side, 1)}
    return quad, diag


def warp_page(bgr, quad, tpl, px_per_mm=8.0, page_idx=0):
    """透视矫正到与模板一致的 mm 网格 → 返回 (矫正图, px_per_mm)
    目标点用「模板里的定位点坐标」（不是纸张四角）—— 检测到的 quad 是定位点中心，
    两者必须一一对应，否则整体坐标会差一个定位点内缩量。"""
    W, H = float(tpl['paper']['w']), float(tpl['paper']['h'])
    dst_mm, _ = _template_quad(tpl, page_idx)
    ow, oh = int(round(W * px_per_mm)), int(round(H * px_per_mm))
    dst = dst_mm * px_per_mm
    Hm = cv2.getPerspectiveTransform(quad, dst)
    warp = cv2.warpPerspective(bgr, Hm, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    return warp, px_per_mm


def _prep(warp):
    """矫正图 → (归一化灰度图, 二值图)。选择题与考号填涂区共用同一套预处理 ——
    两条路必须用完全一样的阈值，否则「选择题读得准、考号读不准」这种差异没法解释。"""
    gray = cv2.cvtColor(warp, cv2.COLOR_BGR2GRAY)
    norm = _lighting_normalize(gray)
    thr = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return norm, thr


def _sample(norm, thr, opts, px_per_mm, shrink=SHRINK):
    """采样一组框。opts: [{'opt', x, y, w, h}]（mm）→ [{'opt','ratio','ink',...}]"""
    out = []
    for o in opts:
        cx, cy = o['x'] * px_per_mm, o['y'] * px_per_mm
        rx = max(1.0, o['w'] * shrink * px_per_mm / 2.0)
        ry = max(1.0, o['h'] * shrink * px_per_mm / 2.0)
        x0, x1 = int(round(cx - rx)), int(round(cx + rx)) + 1
        y0, y1 = int(round(cy - ry)), int(round(cy + ry)) + 1
        tpatch = thr[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
        gpatch = norm[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
        ratio = float((tpatch > 0).mean()) if tpatch.size else 0.0
        ink = float(((255.0 - gpatch) / 255.0).mean()) if gpatch.size else 0.0
        out.append({'opt': o['opt'], 'ratio': round(ratio, 3), 'ink': round(ink, 3),
                    'x': o['x'], 'y': o['y'], 'w': o['w'], 'h': o['h']})
    return out


def sample_bubbles(warp, page, px_per_mm, shrink=SHRINK):
    """按模板坐标采样每个填涂圈。
    每个选项输出两个量：
      ratio — 二值化后的深色像素占比（对光照鲁棒，用于区分「涂了 vs 没涂」）
      ink   — 灰度墨迹均值 (0~1)（用于区分「深涂 vs 浅涂」：中灰色铅笔也要能识别）"""
    norm, thr = _prep(warp)
    return [{'no': q['no'], 'options': _sample(norm, thr, q.get('options', []), px_per_mm, shrink)}
            for q in page.get('questions', [])]


def decode_sid(warp, page, px_per_mm, fill_min=0.5, shrink=SHRINK):
    """解码考号填涂区。没有这一块时返回 None。

    每一列是一位数字，列内 10 个格子取墨迹最重的那个当这一位的数字 ——
    和选择题是同一种「相对基线」判定，所以同一张扫描件的稳定性一致。

    返回 {'text', 'digits', 'positions', 'ok', 'filled', 'flags'}
      text      — 读出来的考号（没涂的位用 '?' 占位，保持位数对齐）
      ok        — 每一位都判得干净利落（没有 blank / faint / doubt）
      positions — 逐位明细（pos / digit / flag / ink / second）
    """
    sid = page.get('sid')
    if not sid or not sid.get('positions'):
        return None
    norm, thr = _prep(warp)

    chars, positions, flags = [], [], []
    for p in sid['positions']:
        bubbles = p.get('bubbles') or []
        sampled = _sample(norm, thr, [dict(b, opt=str(b.get('digit'))) for b in bubbles],
                          px_per_mm, shrink)
        if not sampled:
            chars.append('?')
            positions.append({'pos': p['pos'], 'digit': None, 'flag': 'blank',
                              'ink': 0.0, 'second': 0.0})
            flags.append('blank')
            continue
        base = min(s['ink'] for s in sampled)
        s = sorted(sampled, key=lambda x: -x['ink'])
        best = s[0]
        second = s[1] if len(s) > 1 else {'ink': 0.0, 'opt': ''}
        rel = best['ink'] - base
        rel2 = second['ink'] - base
        if rel < SID_REL_MIN:
            flag, digit = 'blank', None
        elif rel2 >= rel - SID_GAP and rel2 >= SID_SECOND_MIN:
            flag, digit = 'doubt', best['opt']        # 一列涂了两个 / 涂得太糊
        elif best['ink'] < fill_min:
            flag, digit = 'faint', best['opt']        # 涂了但很浅
        else:
            flag, digit = 'ok', best['opt']
        chars.append(digit if digit is not None else '?')
        flags.append(flag)
        # 连坐标一起回吐：校对图要圈出这一位实际选中的格子，不能让它再去模板里翻
        positions.append({'pos': p['pos'], 'digit': digit, 'flag': flag,
                          'ink': round(best['ink'], 3), 'second': round(second['ink'], 3),
                          'x': best['x'], 'y': best['y'], 'w': best['w'], 'h': best['h']})

    text = ''.join(chars)
    filled = sum(1 for c in chars if c != '?')
    return {'text': text, 'digits': len(chars), 'positions': positions,
            'ok': all(f == 'ok' for f in flags), 'filled': filled, 'flags': flags}


def decide(sampled, fill_min=0.5, gap=0.15, rel_min=0.15, second_rel_min=0.2):
    """判定每题答案。返回 list of {no, answer, flag, ratios(二值占比), inks(墨迹)}
    判定用墨迹均值 ink 的「相对基线」：圈内印着字母（本身就是深色），未涂的框也有
    0.1~0.25 的墨迹，绝对阈值不可靠。rel = best - min(各选项 ink)。
    flag: ok / multi（多选或难分） / faint（浅涂，存疑） / blank（未填）

    second_rel_min —— 判「多选」时，次优选项自己也得够深。**四个印刷字母之间的 ink
    极差就有 0.08 上下**（实测空白题 q3 是 0.079），所以只看 `rel2 >= rel - gap` 时，
    浅涂题会踩在噪声地板上：浅涂 A（0.388）的次优是印刷字母 D（0.243），rel2 只比
    rel-gap 高 0.005，于是一道「A 涂得太轻」被报成「A 和 D 都涂了」。次优必须真的
    是墨迹（默认 ≥0.2）才叫多选，否则退回 faint —— 两个 flag 都会进复核队列，
    但 faint 指向的是正确答案，multi 会让人以为有两个答案。
    """
    res = []
    for q in sampled:
        inks = {o['opt']: o['ink'] for o in q['options']}
        ratios = {o['opt']: o['ratio'] for o in q['options']}
        base = min(inks.values())
        s = sorted(q['options'], key=lambda o: -o['ink'])
        best, second = s[0], (s[1] if len(s) > 1 else {'ink': 0.0, 'opt': ''})
        rel = best['ink'] - base
        rel_second = second['ink'] - base
        if rel < rel_min:
            flag, ans = 'blank', None
        elif rel_second >= rel - gap and rel_second >= second_rel_min:
            flag, ans = 'multi', best['opt']
        elif best['ink'] < fill_min:
            flag, ans = 'faint', best['opt']
        else:
            flag, ans = 'ok', best['opt']
        res.append({'no': q['no'], 'answer': ans, 'flag': flag, 'ratios': ratios, 'inks': inks,
                    'best': round(best['ink'], 3), 'second': round(second['ink'], 3)})
    return res


def draw_overlay(warp, sampled, results, px_per_mm, scale=1.0, sid=None):
    """生成校对图：绿=已选，红=存疑，灰=未选；并标注墨迹均值。

    考号填涂区一并画出来（选中的数字圈绿/红圈 + 圈旁标墨迹值）——
    考号读错了是整份卷子归错人的那种错误，必须让人一眼能核。
    """
    img = warp.copy()
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    k = px_per_mm * scale
    res_by_no = {r['no']: r for r in results}
    for q in sampled:
        r = res_by_no.get(q['no'], {})
        ans, flag = r.get('answer'), r.get('flag')
        for o in q['options']:
            cx, cy = int(round(o['x'] * k)), int(round(o['y'] * k))
            r_px = max(4, int(round(max(o['w'], o['h']) * k * 0.62)))
            if ans == o['opt'] and flag == 'ok':
                color = (40, 170, 60)
            elif ans == o['opt']:
                color = (40, 60, 230)
            else:
                color = (150, 150, 150)
            thick = 3 if ans == o['opt'] else 1
            cv2.circle(img, (cx, cy), r_px, color, thick)
            ink = r.get('inks', {}).get(o['opt'])
            if ans == o['opt'] or (ink or 0) > 0.3:
                cv2.putText(img, f"{int((ink or 0) * 100)}", (cx + r_px + 2, cy + 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)

    for pos in (sid or {}).get('positions', []):
        flag = pos.get('flag')
        if pos.get('digit') is None or not pos.get('w'):
            continue                                   # 这一位没涂出来，没圈可画
        color = (40, 170, 60) if flag == 'ok' else ((150, 150, 150) if flag == 'blank' else (40, 60, 230))
        cx, cy = int(round(pos['x'] * k)), int(round(pos['y'] * k))
        r_px = max(4, int(round(max(pos['w'], pos['h']) * k * 0.62)))
        cv2.circle(img, (cx, cy), r_px, color, 3)
        cv2.putText(img, f"{pos['pos']}:{pos['digit']}", (cx + r_px + 2, cy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)
    return img


def recognize(image_bgr, tpl, page_idx=0, px_per_mm=8.0, fill_min=0.5, gap=0.15, overlay=True):
    """完整识别流程：定位 → 矫正 → 采样 → 判定（含考号填涂区）"""
    quad, diag = detect_marks(image_bgr, tpl, page_idx)
    warp, px = warp_page(image_bgr, quad, tpl, px_per_mm, page_idx)
    _, real_idx = _template_quad(tpl, page_idx)
    page = tpl['pages'][real_idx]
    sampled = sample_bubbles(warp, page, px)
    results = decide(sampled, fill_min=fill_min, gap=gap)
    sid = decode_sid(warp, page, px, fill_min=fill_min)
    out = {'page': real_idx, 'questions': results, 'diag': diag, 'pxPerMm': px, 'sid': sid}
    if overlay:
        ov = draw_overlay(warp, sampled, results, px,
                          scale=min(1.0, 1400.0 / warp.shape[1]), sid=sid)
        ok_, buf = cv2.imencode('.png', ov)
        if ok_:
            out['overlayPng'] = buf.tobytes()
    return out
