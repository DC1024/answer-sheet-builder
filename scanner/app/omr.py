# 答题卡扫描识别核心：四角定位点透视矫正 + 阅卷模板坐标采样判定填涂。
# 全流程纯 OpenCV/NumPy，不下载任何模型，CPU 即可运行，可完全离线。
import json
import math
import numpy as np
import cv2

FORMAT = 'asb-omr/1'

# 采样框相对填涂圈方框的收缩比例（避开印刷的方括号边框）
SHRINK = 0.60


class OmrError(Exception):
    pass


def load_template(src):
    """src 可以是 JSON 字符串、bytes 或已解析的 dict"""
    tpl = json.loads(src) if isinstance(src, (str, bytes, bytearray)) else src
    if not isinstance(tpl, dict) or tpl.get('format') != FORMAT:
        raise OmrError(f'不是有效的阅卷模板（format 应为 {FORMAT}）')
    if not tpl.get('pages'):
        raise OmrError('模板里没有任何面（pages 为空）')
    return tpl


def template_summary(tpl):
    pages = tpl.get('pages', [])
    return {
        'format': tpl.get('format'),
        'paper': tpl.get('paper'),
        'marks': tpl.get('marks'),
        'pages': [{'index': p.get('index', i), 'questions': len(p.get('questions', []))}
                  for i, p in enumerate(pages)],
        'questionCount': tpl.get('questionCount') or sum(len(p.get('questions', [])) for p in pages),
        'questionNumbers': sorted({q['no'] for p in pages for q in p.get('questions', [])}),
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


def sample_bubbles(warp, page, px_per_mm, shrink=SHRINK):
    """按模板坐标采样每个填涂圈。
    每个选项输出两个量：
      ratio — 二值化后的深色像素占比（对光照鲁棒，用于区分「涂了 vs 没涂」）
      ink   — 灰度墨迹均值 (0~1)（用于区分「深涂 vs 浅涂」：中灰色铅笔也要能识别）"""
    gray = cv2.cvtColor(warp, cv2.COLOR_BGR2GRAY)
    norm = _lighting_normalize(gray)
    thr = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    out = []
    for q in page.get('questions', []):
        opts = []
        for o in q.get('options', []):
            cx, cy = o['x'] * px_per_mm, o['y'] * px_per_mm
            rx = max(1.0, o['w'] * shrink * px_per_mm / 2.0)
            ry = max(1.0, o['h'] * shrink * px_per_mm / 2.0)
            x0, x1 = int(round(cx - rx)), int(round(cx + rx)) + 1
            y0, y1 = int(round(cy - ry)), int(round(cy + ry)) + 1
            tpatch = thr[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
            gpatch = norm[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
            ratio = float((tpatch > 0).mean()) if tpatch.size else 0.0
            ink = float(((255.0 - gpatch) / 255.0).mean()) if gpatch.size else 0.0
            opts.append({'opt': o['opt'], 'ratio': round(ratio, 3), 'ink': round(ink, 3),
                         'x': o['x'], 'y': o['y'], 'w': o['w'], 'h': o['h']})
        out.append({'no': q['no'], 'options': opts})
    return out


def decide(sampled, fill_min=0.5, gap=0.15, rel_min=0.15):
    """判定每题答案。返回 list of {no, answer, flag, ratios(二值占比), inks(墨迹)}
    判定用墨迹均值 ink 的「相对基线」：圈内印着字母（本身就是深色），未涂的框也有
    0.1~0.25 的墨迹，绝对阈值不可靠。rel = best - min(各选项 ink)。
    flag: ok / multi（多选或难分） / faint（浅涂，存疑） / blank（未填）"""
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
        elif rel_second >= rel - gap:
            flag, ans = 'multi', best['opt']
        elif best['ink'] < fill_min:
            flag, ans = 'faint', best['opt']
        else:
            flag, ans = 'ok', best['opt']
        res.append({'no': q['no'], 'answer': ans, 'flag': flag, 'ratios': ratios, 'inks': inks,
                    'best': round(best['ink'], 3), 'second': round(second['ink'], 3)})
    return res


def draw_overlay(warp, sampled, results, px_per_mm, scale=1.0):
    """生成校对图：绿=已选，红=存疑，灰=未选；并标注墨迹均值"""
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
    return img


def recognize(image_bgr, tpl, page_idx=0, px_per_mm=8.0, fill_min=0.5, gap=0.15, overlay=True):
    """完整识别流程：定位 → 矫正 → 采样 → 判定"""
    quad, diag = detect_marks(image_bgr, tpl, page_idx)
    warp, px = warp_page(image_bgr, quad, tpl, px_per_mm, page_idx)
    _, real_idx = _template_quad(tpl, page_idx)
    page = tpl['pages'][real_idx]
    sampled = sample_bubbles(warp, page, px)
    results = decide(sampled, fill_min=fill_min, gap=gap)
    out = {'page': real_idx, 'questions': results, 'diag': diag, 'pxPerMm': px}
    if overlay:
        ov = draw_overlay(warp, sampled, results, px, scale=min(1.0, 1400.0 / warp.shape[1]))
        ok_, buf = cv2.imencode('.png', ov)
        if ok_:
            out['overlayPng'] = buf.tobytes()
    return out
