# -*- coding: utf-8 -*-
"""手写字母结构分类（A/B/C/D，大小写均收）：纯 OpenCV 特征，零模型、可离线。

思路：不做 OCR —— A/B/C/D 四个字母的**拓扑结构差异**远大于笔迹风格差异：
  B 有 2 个洞；C 没有洞；A / D / a / b / d 各 1 个洞，但洞的位置与
  字形轮廓（顶宽 / 底宽 / 起笔侧）可区分：
    A  洞在上中部 + 底部张开（两腿）
    D  洞大且几乎贯穿全高 + 顶部平
    a  洞在下半部 + 上方有右钩弧
    b  洞在右下 + 左侧长竖（上端有墨）
    d  洞在左下 + 右侧长竖
打分制而非硬规则：每个特征给候选字母加减分，取最高分；最高与次高之差
作为置信度，低于阈值交复核（flag=doubt），不硬猜。
"""
import cv2
import numpy as np

# 归一化画布
CANVAS = 48
# 洞面积下限（占字形面积比例）—— 小于此的洞视为笔画缝隙噪声
HOLE_MIN = 0.03
# 置信度低于它 → doubt（交老师复核，不硬猜）
DOUBT_CONF = 1.0


def extract_glyph(thr_box, min_area_ratio=0.02):
    """从作答框的二值图（墨=255）提取字形紧致掩码。

    返回 (glyph 48x48 uint8 {0,255}, meta) 或 (None, meta)。
    meta: {'blobs': 连通域数, 'area': 墨面积}
    噪声剔除：面积 < 框面积 min_area_ratio 的连通域忽略；
    断笔合并：在 3x3 膨胀图上找连通域，回原掩码取像素。
    """
    h, w = thr_box.shape
    box_area = float(h * w)
    if box_area < 25:
        return None, {'blobs': 0, 'area': 0}
    ink = int((thr_box > 0).sum())
    if ink < box_area * min_area_ratio:
        return None, {'blobs': 0, 'area': ink}

    dil = cv2.dilate(thr_box, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(dil, connectivity=8)
    comps = []                                       # (area, x, y, bw, bh)
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < box_area * min_area_ratio:
            continue
        comps.append((a, stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]))
    if not comps:
        return None, {'blobs': 0, 'area': ink}
    comps.sort(key=lambda c: -c[0])
    main = comps[0]
    meta = {'blobs': len(comps), 'area': int(main[0])}

    # 次大连通域仍占主体 1/4 以上 → 大概率写了两个字母
    if len(comps) > 1 and comps[1][0] > main[0] * 0.25:
        return None, dict(meta, multi=True)

    # 主字形 + 与主域**有墨重叠**或面积可观的连通域（断笔 / 点类）一起收进掩码。
    # 只判「包围盒相交」会混入邻字杂墨（采样框沾到相邻字母的边缘），必须用墨重叠。
    mx0, my0, mx1, my1 = main[1], main[2], main[1] + main[3], main[2] + main[4]
    mask = np.zeros_like(thr_box)
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < box_area * min_area_ratio:
            continue
        x, y, bw, bh = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
        bbox = thr_box[y:y + bh, x:x + bw]
        if bbox.size == 0:
            continue
        # 该连通域是否与主域包围盒有墨重叠：两区域矩形交集内有墨即算
        ix0, iy0 = max(x, mx0), max(y, my0)
        ix1, iy1 = min(x + bw, mx1), min(y + bh, my1)
        overlap_ink = False
        if ix1 > ix0 and iy1 > iy0:
            # 该连通域内、且落在主域包围盒里的墨
            sub = bbox[iy0 - y:iy1 - y, ix0 - x:ix1 - x]
            overlap_ink = bool((sub > 0).any())
        if overlap_ink or a >= main[0] * 0.10:
            mask[y:y + bh, x:x + bw] |= bbox
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None, meta
    g = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return _normalize(g), meta


def _normalize(g):
    """保持长宽比缩放进 CANVAS 画布，居中补白。"""
    gh, gw = g.shape
    s = (CANVAS - 4) / max(gh, gw)
    nw, nh = max(1, int(round(gw * s))), max(1, int(round(gh * s)))
    r = cv2.resize(g, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((CANVAS, CANVAS), np.uint8)
    y0, x0 = (CANVAS - nh) // 2, (CANVAS - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = r
    return canvas


def _holes(g):
    """洞列表：[(area, x, y, w, h)]（画布坐标）。

    方法：对反色图做连通域，凡「不触碰画布四边」的反色区就是洞（被字形完整包围）。
    关键点：外部背景可能被杂墨/断笔切成多段，必须逐连通域看是否触边，而不能
    只从 (0,0) floodFill 一次 —— 否则粘连的邻字墨会把外部背景封住，把本该是
    背景的区域误判成洞（这是早期 226/900 全部误判成 B 的根因）。
    """
    inv = cv2.bitwise_not(g)
    n, _, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    garea = max(1, int((g > 0).sum()))
    holes = []
    h, w = g.shape
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < garea * HOLE_MIN:
            continue
        x, y, bw, bh = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
        # 触到画布任何一边 → 是外部背景，不是洞
        if x == 0 or y == 0 or x + bw >= w or y + bh >= h:
            continue
        holes.append((a, x, y, bw, bh))
    holes.sort(key=lambda h_: -h_[0])
    return holes


def _features(g):
    holes = _holes(g)
    ys, xs = np.nonzero(g)
    h = CANVAS
    f = {
        'nh': len(holes),
        'aspect': round((xs.max() - xs.min() + 1) / max(1, ys.max() - ys.min() + 1), 2),
    }
    if holes:
        a, x, y, w, hh = holes[0]                    # 最大洞
        f['hole_a'] = a / max(1, int((g > 0).sum()))
        f['hole_cx'] = (x + w / 2) / h
        f['hole_cy'] = (y + hh / 2) / h
        f['hole_h'] = hh / h
        f['hole_w'] = w / h
    else:
        f.update(hole_a=0, hole_cx=0.5, hole_cy=0.5, hole_h=0, hole_w=0)
    # 顶/底 18% 行带的墨宽度（占字形宽比例）
    ys0, ys1 = ys.min(), ys.max()
    gh = max(1, ys1 - ys0 + 1)
    band = max(2, int(gh * 0.18))

    def _band_w(y_from, y_to):
        sl = g[y_from:y_to]
        cols = np.nonzero(sl.any(axis=0))[0]
        return (cols.max() - cols.min() + 1) / CANVAS if len(cols) else 0.0

    f['top_w'] = round(_band_w(ys0, ys0 + band), 2)
    f['bot_w'] = round(_band_w(ys1 - band + 1, ys1 + 1), 2)
    # 顶部 30% 行带里，左右哪侧有墨（b 的左竖 / d 的右竖 / A 的尖顶居中）
    tband = g[ys0:ys0 + max(2, int(gh * 0.30))]
    cols = np.nonzero(tband.any(axis=0))[0]
    if len(cols):
        mid = CANVAS / 2
        f['top_left'] = int((cols < mid * 0.8).sum())
        f['top_right'] = int((cols > mid * 1.2).sum())
    else:
        f['top_left'] = f['top_right'] = 0
    return f


def classify(glyph):
    """glyph: 48x48 {0,255} → {'letter','conf','features'} 或 None（空）。

    打分规则（调参基准：real30 印刷体 ~900 样本须 ≥99%；真实笔迹待素材）。
    """
    if glyph is None:
        return None
    f = _features(glyph)
    s = {'A': 0.0, 'B': 0.0, 'C': 0.0, 'D': 0.0}

    # --- 洞数是第一判据 ---
    if f['nh'] == 0:
        s['C'] += 1.6
        s['A'] -= 0.8                               # 没封口的 A 会被 C 抢走 → 洞很关键
        s['B'] -= 0.6
        s['D'] -= 0.6
        # C 是瘦长开放形；若是矮胖方形（A/B/D 破坏到洞丢失），C 不应太自信
        if f['aspect'] > 0.85:
            s['C'] -= 0.4
    elif f['nh'] >= 2:
        s['B'] += 2.0
        if f['nh'] == 2 and f['hole_h'] < 0.45:
            s['B'] += 0.5                            # b/B 上下双环偏小
    else:                                            # 1 个洞：A/D/a/b/d
        s['A'] += 1.0
        s['D'] += 1.0
        ha, hcy, hch, hcx = f['hole_a'], f['hole_cy'], f['hole_h'], f['hole_cx']
        # 洞宽窄（<0.42）→ B 的双环上下连通成了一个细长洞（real30 实测 B 宽 0.35 vs D 0.51）
        if f['hole_w'] < 0.42:
            s['B'] += 1.4
            s['D'] -= 0.8
        # D：洞大且贯穿
        if hch > 0.55:
            s['D'] += 1.0
            s['A'] -= 0.6
        # A：洞在上中部；a：洞在下半部（都归 A）
        if 0.20 <= hcy <= 0.58 and hch < 0.55:
            s['A'] += 0.8
            s['D'] -= 0.4
        if hcy > 0.58:
            s['A'] += 0.5                            # a 的洞靠下
            s['D'] -= 0.5
        # A 两腿张开：底宽明显大于顶宽
        if f['bot_w'] - f['top_w'] > 0.12:
            s['A'] += 0.7
        # D 顶部平
        if f['top_w'] > 0.55:
            s['D'] += 0.6
            s['A'] -= 0.3
        # b / d：顶部墨偏一侧
        tl, tr = f['top_left'], f['top_right']
        if tl > tr * 2 and tl > 2:
            s['B'] += 1.2                            # 左侧长竖 → b
            s['D'] -= 0.8
            s['A'] -= 0.4
        if tr > tl * 2 and tr > 2:
            s['D'] += 1.0                            # 右侧长竖 → d（或 D 的圆弧，需洞位佐证）
            if hcx < 0.45:
                s['D'] += 0.5                        # 洞偏左 → 小写 d 特征
                s['A'] -= 0.5
        # a：洞偏右下 + 顶部有横跨弧
        if hcy > 0.58 and hcx > 0.5:
            s['A'] += 0.4
            s['D'] -= 0.3

    best = max(s, key=lambda k: s[k])
    rest = sorted(s.values(), reverse=True)
    conf = round(rest[0] - rest[1], 2)
    if conf < 1e-9:
        return None
    # 无洞 + 接近方形：C 的开口判据失效（A/B/D 破坏到洞丢失的形态），
    # 这类字形不配高置信 —— 压缩 conf，逼它进复核。
    if f['nh'] == 0 and f['aspect'] >= 0.85:
        conf = round(conf * 0.3, 2)
    return {'letter': best, 'conf': conf, 'features': f}


def classify_box(thr_box):
    """作答框二值图 → ({letter, conf, ...}, meta)。空框返回 (None, meta)。"""
    glyph, meta = extract_glyph(thr_box)
    if glyph is None:
        return None, meta
    r = classify(glyph)
    if r is None:
        return None, meta
    if meta.get('multi'):
        r['flag_hint'] = 'multi'
    elif r['conf'] < DOUBT_CONF:
        r['flag_hint'] = 'doubt'
    return r, meta
