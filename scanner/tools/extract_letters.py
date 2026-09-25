# -*- coding: utf-8 -*-
"""从 real30 矫正图提取印刷体 A-D 字母样本 —— 手写分类器的「下限测试集」。

每张卷 10 题 × 4 选项，涂掉的那个是实心方块（跳过），其余 3 个是印刷字母
（标签即选项字母）。30 张 ≈ 900 样本，全部经过真实定位→矫正链路。

输出：tests/fixtures/real30/letters/{A,B,C,D}/NNN.png（48x48 归一化掩码）
用法：.venv/Scripts/python.exe tools/extract_letters.py
"""
import os, sys, json
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import omr, hwletter  # noqa: E402

FIX = os.path.join(HERE, '..', 'tests', 'fixtures', 'real30')
OUT = os.path.join(FIX, 'letters')
SHRINK = 0.72          # 选项框内缩采样，避开印刷框线


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    tpl = omr.load_template(open(os.path.join(FIX, 'template.json'), encoding='utf-8').read())
    expected = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))['sheets']
    os.makedirs(OUT, exist_ok=True)
    for d in 'ABCD':
        os.makedirs(os.path.join(OUT, d), exist_ok=True)

    files = sorted(f for f in os.listdir(FIX) if f.endswith('.png'))
    counts = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
    manifest = []
    for fn in files:
        key = fn.split('_')[0].replace('第', '').replace('份', '')
        bgr = imread_cn(os.path.join(FIX, fn))
        quad, _ = omr.detect_marks(bgr, tpl)
        warp, px = omr.warp_page(bgr, quad, tpl, px_per_mm=15.11)
        norm, thr = omr._prep(warp)
        page = tpl['pages'][0]
        for q in page['questions']:
            filled = expected[key]['answers'][str(q['no'])]
            for o in q['options']:
                if o['opt'] == filled:
                    continue                       # 涂黑的方块，不是字母
                cx, cy = o['x'] * px, o['y'] * px
                rx, ry = o['w'] * SHRINK * px / 2, o['h'] * SHRINK * px / 2
                box = thr[int(cy - ry):int(cy + ry) + 1, int(cx - rx):int(cx + rx) + 1]
                glyph, meta = hwletter.extract_glyph(box)
                if glyph is None:
                    print(f'!! {fn} q{q["no"]}{o["opt"]}: 未提出字形 {meta}')
                    continue
                lbl = o['opt']
                idx = counts[lbl]
                counts[lbl] += 1
                name = f'{key}_{q["no"]:02d}_{lbl}_{idx:04d}.png'
                cv2.imencode('.png', glyph)[1].tofile(os.path.join(OUT, lbl, name))
                manifest.append({'file': f'{lbl}/{name}', 'label': lbl,
                                 'sheet': key, 'q': q['no']})
    with open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    print('样本数:', counts, '合计', sum(counts.values()))


if __name__ == '__main__':
    main()
