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


def extract_glyph(thr_box, min_area_ratio=0.02, frame_th=0.82):
    """从作答框的二值图（墨=255）提取字形紧致掩码。

    返回 (glyph 48x48 uint8 {0,255}, meta) 或 (None, meta)。
    meta: {'blobs': 保留的连通域数, 'area': 主字形面积,
           'frame_drop': 被判为框线剔除的段数, 'raw_blobs': 剔除前的连通域数}
    噪声剔除：面积 < 框面积 min_area_ratio 的连通域忽略；
    断笔合并：在 3x3 膨胀图上找连通域，回原掩码取像素。

    作答框边框：模板的 write 框常常印有可见黑框。二值化后框线是一个
    **外接矩形几乎占满整个采样框**的连通域（宽/高都 ≥ frame_th），
    它不是手写字母，必须在提字形前剔除 —— 否则框 + 字母两个大块会被
    当成 multi（=“写了两字母”），或框线特征把分类带偏（实测 1/3 判 multi、
    答案偏 C 就是这个原因）。

    真实卷里更常见的是方框**断成多段**（左竖/右竖/上下横/四角），每段
    都不满足 frame_th → 由 _is_frame_piece 按「贴边+细长 / 贴边角块」剔除。
    剔除只作用于非主连通域，写得满框的大字不会被误删。
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

    def _is_frame(i):
        """整个外接矩形几乎铺满采样框 → 是纸面方框的边框，不是手写字母。"""
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        return bw > frame_th * w and bh > frame_th * h

    def _is_frame_piece(i):
        """框线**碎片**：纸面方框被断笔/二值化切成多段后，每一段单独的形态。

        完整方框（_is_frame）只占少数 —— 实测真实卷里方框大多断成：
          左竖线 / 右竖线 / 上横线 / 下横线 / 四角拐角
        每一段的外接矩形都很小（bw/w 只有 0.05~0.09），**不满足 frame_th**
        判据，于是被当成手写字的墨留下来：主字形旁边多出一块面积不小的
        “第二大团墨” → 直接触发 multi（Q5/Q10 实测 28/30 卷判 multi 就是它）。

        判据（贴边 + 细长，或贴边的角块）：手写字母写在框中央，不会
        恰好细长地贴在采样框边缘，也不会孤立地卡在角落而不与主字相连。
        """
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        x, y = stats[i, 0], stats[i, 1]
        thin_x = bw < 0.15 * w                       # 竖向细条（框的竖边）
        thin_y = bh < 0.15 * h                       # 横向细条（框的横边）
        touch_l, touch_r = x <= 1, (x + bw) >= w - 1
        touch_t, touch_b = y <= 1, (y + bh) >= h - 1
        if thin_x and (touch_l or touch_r):
            return True
        if thin_y and (touch_t or touch_b):
            return True
        # 拐角：同时贴住两条边（横竖边在角上断开了）
        if (touch_l or touch_r) and (touch_t or touch_b):
            return True
        return False

    # 先收集所有够大的连通域，按面积降序 —— 主字形 = 最大者，永远保留，
    # 框线判据只作用于其余碎片（否则写得满框的大字会被误删）。
    comps = []                                       # (area, idx, x, y, bw, bh)
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < box_area * min_area_ratio:
            continue
        comps.append((a, i, stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]))
    if not comps:
        return None, {'blobs': 0, 'area': ink}
    comps.sort(key=lambda c: -c[0])

    keep = [comps[0]]                                # 主字形
    frame_drop = 0
    for c in comps[1:]:
        i = c[1]
        if _is_frame(i) or _is_frame_piece(i):
            frame_drop += 1
            continue
        keep.append(c)
    main = keep[0]
    meta = {'blobs': len(keep), 'area': int(main[0]),
            'frame_drop': frame_drop, 'raw_blobs': len(comps)}

    # 次大连通域仍占主体 1/4 以上 → 可能写了两个字母。
    # 但真实手写里**同一个字母常被断笔切成上下两段**（横杠、收笔与主体分离），
    # 形态上也是「两大团墨」，却不是两个字 —— 直接按面积判 multi 会冤枉它们
    # （实测 48 个残留 multi 多数是这种）。区分方法看**空间关系**：
    #   两个字母并排写 → 次大域在主体左/右侧，包围盒基本不重叠
    #   同一字母断笔   → 次大域在主体上/下方且大量落在主体包围盒内
    mx0, my0, mx1, my1 = main[2], main[3], main[2] + main[4], main[3] + main[5]
    if len(keep) > 1 and keep[1][0] > main[0] * 0.25:
        c = keep[1]
        ix0, iy0 = max(c[2], mx0), max(c[3], my0)
        ix1, iy1 = min(c[2] + c[4], mx1), min(c[3] + c[5], my1)
        inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
        # 包围盒重叠不足一半 → 空间上确实是分开的第二团 → 才判 multi
        if inter < 0.5 * max(1, c[4] * c[5]):
            return None, dict(meta, multi=True)
    mask = np.zeros_like(thr_box)
    for c in keep:
        a, i, x, y, bw, bh = c
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
    def _side_ink(y_from, y_to):
        """某行带里左半 / 右半各有多少列有墨 —— 用来判断「环是否闭合」。"""
        sl = g[y_from:y_to]
        cols = np.nonzero(sl.any(axis=0))[0]
        if not len(cols):
            return 0, 0
        mid = CANVAS / 2
        return int((cols < mid * 0.8).sum()), int((cols > mid * 1.2).sum())

    f['top_left'], f['top_right'] = _side_ink(ys0, ys0 + max(2, int(gh * 0.30)))
    # 中部行带（40%~60%）的左右墨 —— 零洞时区分「C 的右开口」与「A/D 的环」的关键：
    #   C 中部只有左侧有墨（右侧敞开）→ mid_right≈0
    #   D 中部左右都有墨（半圆环，只是笔画没收拢没检出洞）→ mid_right 大
    #   A 的两腿 / B 的双环同理都有右侧墨
    f['mid_left'], f['mid_right'] = _side_ink(ys0 + int(gh * 0.40), ys0 + max(int(gh * 0.60), int(gh * 0.40) + 1))

    # 上/中/下 三段的墨密度 —— 区分 D 的半圆与 B 的双环：
    #   D 的中部是空的（只剩左竖 + 右弧两条边）→ 中部墨 ≈ 甚至少于两端
    #   B 的两个环在中部交汇成"腰"       → 中部墨明显多于两端
    # 实测真值 D 的「中部−两端」≈ 0.00，真值 B ≈ +0.15，方向相反，判别力很强。
    def _band_ink(y_from, y_to):
        sl = g[max(0, y_from):max(0, y_to)]
        return float((sl > 0).sum()) / max(1, sl.size)

    s1, s2 = int(gh * 0.33), int(gh * 0.67)
    i_top = _band_ink(ys0, ys0 + max(1, s1))
    i_mid = _band_ink(ys0 + s1, ys0 + max(s2, s1 + 1))
    i_bot = _band_ink(ys0 + s2, ys1 + 1)
    f['ink_top'] = round(i_top, 3)
    f['ink_mid'] = round(i_mid, 3)
    f['ink_bot'] = round(i_bot, 3)
    ends = (i_top + i_bot) / 2.0
    f['mid_over_ends'] = round(i_mid / ends, 3) if ends > 1e-6 else 1.0
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
        # 真实手写里 A/B/D 的洞经常**收不拢口**（起收笔有缝）→ nh=0，
        # 早期版本在这里一律 s['C'] += 1.6，实测 153 个零洞样本全判成 C，
        # 其中 98 个真值是 A/B/D —— 这是准确率最大的杀手。
        # 洞没了不代表形状没了：用「中部行带左右是否都有墨」把
        # **右开口的 C** 和 **左右合围的环（A/B/D）** 先劈开，再看形态定字母。
        #   C  中部只有左侧有墨（向右敞开）  → mid_right≈0
        #   D  中部左右都有墨且右侧更重（半圆弧）→ md = mr-ml 明显为正
        #   A  两腿张开 → 底宽明显大于顶宽
        #   B  左右都有墨且较均衡（双环）
        mr, ml = f['mid_right'], f['mid_left']
        md = mr - ml
        dw = f['bot_w'] - f['top_w']
        if mr <= 0:                                  # 右侧敞开 → 真的是 C 的开口
            s['C'] += 1.8
            s['A'] -= 0.5
            s['B'] -= 0.3
            s['D'] -= 0.8
        elif md < -4:                                # 左重右轻 → C 的左弧
            s['C'] += 1.2
            s['D'] -= 0.5
        elif dw > 0.25:                              # 底宽 >> 顶宽 → A 的两腿
            s['A'] += 1.5
            s['C'] -= 1.0
        elif f['top_w'] < 0.30:                      # 尖顶 → A
            # 两腿张开得不明显的 A（dw 不够）靠尖顶抓：实测真值 A 顶宽 0.22，
            # 真值 B 顶宽 0.47（B 的上环顶是平的），差一倍多。
            s['A'] += 1.2
            s['B'] -= 0.5
            s['C'] -= 0.8
        elif md > 3.0:                               # 右弧明显偏重 → D
            s['D'] += 1.5
            s['C'] -= 1.0
        elif f['mid_over_ends'] >= 0.95:
            # 中部墨不少于两端 → B 的两个环在这里交汇成「腰」
            s['B'] += 1.2
            s['C'] -= 1.2
        else:
            # 中部比两端空 → D 的半圆：这里只剩左竖 + 右弧两条边
            # （实测真值 D 的 mid_over_ends≈0.91，真值 B≈1.21，方向相反）
            s['D'] += 1.2
            s['C'] -= 1.2
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
        # 洞窄（<0.42）有两种可能：B 的双环上下连通成一个细长洞，或 D 半圆里
        # 那个贯穿全高的竖长洞。用洞的**高宽比**分开 —— 实测被误判成 B 的 D
        # 洞高 0.64 / 洞宽 0.37（比 1.7），而判对的 B 是 0.19 / 0.19（比 1.0）。
        if f['hole_w'] < 0.42:
            if f['hole_h'] > 0.5 and f['top_w'] < 0.45:
                # 竖长且贯穿 + 顶不宽 → D 的半圆内腔。
                # 顶宽这个附加条件是必须的：印刷体 B 的双环上下连通后**同样是
                # 竖长洞**（实测 hole_w 0.35 / hole_h 0.73），但它的上环顶是平的
                # （top_w 0.52），而 D 顶不宽（0.39）—— 只凭洞形会把这类 B 判成 D。
                s['D'] += 1.2
                s['B'] -= 0.4
            else:
                s['B'] += 1.4
                s['D'] -= 0.8
        # 尖顶 vs 平顶（同零洞分支的判据，实测 A 顶宽 0.22 / B 0.47）
        if f['top_w'] < 0.30:
            s['A'] += 1.0
            s['B'] -= 0.6
            s['D'] -= 0.4
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
