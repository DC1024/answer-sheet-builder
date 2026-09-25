# -*- coding: utf-8 -*-
"""从 30 张真实答题卡逆向生成 asb-omr/2 阅卷模板，并用 omr.recognize 全量回验。

流程：
  1. 每张图找 4 个实心方角定位点（≈40px），得 quad；
  2. 按 quad 透视矫正到 210x297mm 网格；
  3. 在选择题区带（y 35~53mm）检测 4.4~4.9mm 的选项框外轮廓；
  4. 30 张取平均中心 → 按 y 聚成 2 行、按 x 间隔聚成 5 组/行 → 题 1~10 × A~D；
  5. 输出 tests/fixtures/real30/template.json；
  6. 用 omr.recognize 跑全部 30 张，报告每份的答案与 flag。

用法：.venv/Scripts/python.exe tools/make_template_from_real.py [--no-verify]
"""
import sys, os, json, re
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import omr  # noqa: E402

FIX = os.path.join(HERE, '..', 'tests', 'fixtures', 'real30')
TPL_OUT = os.path.join(FIX, 'template.json')

PAPER_W, PAPER_H = 210.0, 297.0
# 选项框外尺寸过滤（mm）
BOX_MIN, BOX_MAX = 4.2, 5.0
# 选择题区带（mm）
BAND_Y0, BAND_Y1 = 35.0, 53.0


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def find_corner_quad(bgr):
    """找 4 个实心方角定位点，返回 tl,tr,br,bl 像素中心。"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
    h, w = bw.shape
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cand = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 400 or a > 8000:
            continue
        x, y, bw_, bh_ = cv2.boundingRect(c)
        ar = bw_ / float(bh_)
        if ar < 0.7 or ar > 1.4:
            continue
        if a / float(bw_ * bh_) < 0.8:
            continue
        cx, cy = x + bw_ / 2.0, y + bh_ / 2.0
        if not (cx < w * 0.12 or cx > w * 0.88):
            continue
        if not (cy < h * 0.06 or cy > h * 0.94):
            continue
        cand.append((cx, cy))
    if len(cand) != 4:
        raise SystemExit(f'定位点候选 {len(cand)} 个（应为 4）')
    tl = min(cand, key=lambda p: p[0] + p[1])
    br = max(cand, key=lambda p: p[0] + p[1])
    tr = max(cand, key=lambda p: p[0] - p[1])
    bl = min(cand, key=lambda p: p[0] - p[1])
    return np.float32([tl, tr, br, bl]), cand


def warp_to_grid(bgr, quad, pxmm):
    dst = np.float32([(4.24, 4.23), (205.96, 4.23), (205.96, 292.77), (4.24, 292.77)]) * pxmm
    # dst 用像素坐标：QUAD_MM * pxmm
    Hm = cv2.getPerspectiveTransform(quad, dst)
    ow, oh = int(round(PAPER_W * pxmm)), int(round(PAPER_H * pxmm))
    return cv2.warpPerspective(bgr, Hm, (ow, oh), flags=cv2.INTER_LINEAR,
                               borderValue=(255, 255, 255))


def detect_option_boxes(warp, pxmm):
    """选择题区带内的选项框（外轮廓），返回 mm 中心列表。"""
    gray = cv2.cvtColor(warp, cv2.COLOR_BGR2GRAY)
    y0, y1 = int(BAND_Y0 * pxmm), int(BAND_Y1 * pxmm)
    band = gray[y0:y1]
    _, bw = cv2.threshold(band, 200, 255, cv2.THRESH_BINARY_INV)
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    pts = []
    for c in cnts:
        x, y, bw_, bh_ = cv2.boundingRect(c)
        wmm, hmm = bw_ / pxmm, bh_ / pxmm
        if not (BOX_MIN < wmm < BOX_MAX and BOX_MIN < hmm < BOX_MAX):
            continue
        pts.append(((x + bw_ / 2.0) / pxmm, (y + y0 + bh_ / 2.0) / pxmm))
    return pts


def cluster_1d(values, gap):
    """按间隔聚簇，返回簇列表（每簇为排序后的原值列表）。"""
    vs = sorted(values)
    clusters, cur = [], [vs[0]]
    for v in vs[1:]:
        if v - cur[-1] <= gap:
            cur.append(v)
        else:
            clusters.append(cur)
            cur = [v]
    clusters.append(cur)
    return clusters


def main():
    verify = '--no-verify' not in sys.argv
    files = sorted(f for f in os.listdir(FIX) if f.endswith('.png'))
    print(f'{len(files)} 张扫描件')

    # --- 逐张矫正 + 检测选项框中心 ---
    all_pts = []          # 每张一个 (N,2) 数组
    per_sheet_counts = []
    for fn in files:
        bgr = imread_cn(os.path.join(FIX, fn))
        h, w = bgr.shape[:2]
        pxmm = min(w / PAPER_W, h / PAPER_H)
        quad, _ = find_corner_quad(bgr)
        warp = warp_to_grid(bgr, quad, pxmm)
        pts = detect_option_boxes(warp, pxmm)
        per_sheet_counts.append(len(pts))
        all_pts.append(pts)
    print('每张检出的选项框数:', sorted(set(per_sheet_counts)))
    if len(set(per_sheet_counts)) != 1:
        print('!! 各张检出数量不一致 —— 取交集策略不可靠，改用第一张为基准')

    # --- 以检出数中位的那张为基准做一一配对，再平均 ---
    med = sorted(per_sheet_counts)[len(per_sheet_counts) // 2]
    base_idx = per_sheet_counts.index(med)
    base = sorted(all_pts[base_idx], key=lambda p: (round(p[1], 1), p[0]))
    acc = np.zeros((len(base), 2))
    n = np.zeros(len(base))
    for pts in all_pts:
        ps = sorted(pts, key=lambda p: (round(p[1], 1), p[0]))
        if len(ps) != len(base):
            continue
        d = np.linalg.norm(np.array(ps) - np.array(base), axis=1)
        if d.max() > 1.5:   # 配对失败（错位过大），跳过这张
            continue
        acc += np.array(ps)
        n += 1
    centers = acc / n[:, None]
    print(f'配对成功 {int(n[0])}/{len(files)} 张，基准框数 {len(base)}')

    # --- 聚类：按 y 分行，行内按 x 分组（组=题，组内 4 个=A~D）---
    ys = centers[:, 1]
    row_ys = [np.mean(c) for c in cluster_1d(ys, 2.0)]
    print('行 y 中心:', [round(v, 2) for v in row_ys])
    if len(row_ys) != 2:
        raise SystemExit(f'行数 {len(row_ys)} != 2，区带设置有问题')

    questions = []
    qno = 0
    for ry in row_ys:
        row_pts = sorted([p for p in centers if abs(p[1] - ry) < 2.5], key=lambda p: p[0])
        xs = [p[0] for p in row_pts]
        groups = cluster_1d(xs, 10.0)     # 组内选项间距 ~6mm，组间 >30mm
        print(f'  行 y={ry:.2f}: {len(groups)} 组，各组 {len(groups)} 选项 -> '
              f'{[len(g) for g in groups]}')
        if any(len(g) != 4 for g in groups):
            raise SystemExit('存在选项数 != 4 的题组，中止')
        for g in groups:
            qno += 1
            opts = []
            for letter, x in zip('ABCD', sorted(g)):
                # 找回该选项的 y（同组 y 一致）
                y = next(p[1] for p in row_pts if abs(p[0] - x) < 0.3)
                opts.append({'opt': letter, 'x': round(x, 2), 'y': round(y, 2),
                             'w': 4.5, 'h': 4.5})
            questions.append({'no': qno,
                              'x': round(opts[0]['x'] - 6.0, 2),
                              'y': round(sum(o['y'] for o in opts) / 4, 2),
                              'options': opts})

    marks_mm = {'tl': [4.24, 4.23], 'tr': [205.96, 4.23],
                'br': [205.96, 292.77], 'bl': [4.24, 292.77]}
    tpl = {
        'format': 'asb-omr/2',
        'paper': {'size': 'A4', 'orientation': 'portrait', 'w': PAPER_W, 'h': PAPER_H},
        'marks': {'style': 'square', 'size': 2.65},
        'questionCount': len(questions),
        'pages': [{'index': 0, 'marks': [dict(pos=k, x=v[0], y=v[1]) for k, v in marks_mm.items()],
                   'questions': questions}],
    }
    with open(TPL_OUT, 'w', encoding='utf-8') as fh:
        json.dump(tpl, fh, ensure_ascii=False, indent=2)
    print(f'模板已写入 {TPL_OUT}（{len(questions)} 题）')
    print('题 1 选项:', json.dumps(questions[0]['options'], ensure_ascii=False))

    if not verify:
        return

    # --- 全量回验 ---
    print('\n=== omr.recognize 全量回验 ===')
    ok_sheets = 0
    results = {}
    for fn in files:
        bgr = imread_cn(os.path.join(FIX, fn))
        try:
            out = omr.recognize(bgr, tpl, overlay=False)
        except omr.OmrError as e:
            print(f'  {fn}: 识别失败 {e}')
            continue
        ans = {r['no']: (r['answer'], r['flag']) for r in out['questions']}
        flags = [f for _, f in ans.values()]
        n_ok = flags.count('ok')
        m = re.match(r'第(\d+)份_(.*)_01\.png', fn)
        key = f'{int(m.group(1)):02d}' if m else fn
        name = m.group(2) if m else ''
        results[key] = {'name': name, 'answers': {str(k): v[0] for k, v in sorted(ans.items())},
                        'flags': {str(k): v[1] for k, v in sorted(ans.items())}}
        status = 'OK' if n_ok == len(flags) else '有存疑'
        print(f'  {fn}: {n_ok}/{len(flags)} ok  '
              f'{"".join(str(ans[i][0]) if ans[i][0] else "?" for i in sorted(ans))}  {status}')
        if n_ok == len(flags):
            ok_sheets += 1
    print(f'\n干净识别 {ok_sheets}/{len(files)}')
    with open(os.path.join(FIX, 'recognized.json'), 'w', encoding='utf-8') as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print('识别结果已写入 recognized.json')


if __name__ == '__main__':
    main()
