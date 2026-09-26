# -*- coding: utf-8 -*-
"""从 real30 的 write box 提取**手写答题字母**样本——CNN 训练集（真值标注）。

与线上 decode_write 使用完全相同的裁剪方式（write 框全幅，无 shrink），
保证导出的字形就是生产分类器看到的输入；标签来自 expected.json（已验证可信）。

⚠️ 关键：real30 里 01–30 是**填涂版**（template.json，无 write 框），
   31–60 才是**手写版**（template_write.json，有 10 个 write 框）。
   本脚本只认 write 框，必须用 template_write.json，否则会产出 0 样本。

注意：real30/letters/ 是**印刷体选项字母**（extract_letters.py 导出），
     它只能做「印刷体下限测试」，绝不能用来训练手写识别器——本脚本导出的是手写体。

前提：expected.json 必须包含 31–60 每题真值，否则对应 sheet 会被跳过。
      （尚无真值时，先跑 tools/gen_candidates.py 生成可快速核对的候选表。）

输出：tests/fixtures/real30/handwritten/{A,B,C,D}/<sheet>_<q>_<truth>_<idx>.png
      tests/fixtures/real30/handwritten/manifest.json
用法：python tools/extract_handwritten.py
"""
import os
import sys
import json
from collections import Counter

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import omr, hwletter  # noqa: E402

FIX = os.path.join(HERE, '..', 'tests', 'fixtures', 'real30')
OUT = os.path.join(FIX, 'handwritten')
IMG_EXT = '.png'


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    # 手写版模板（含 write 框）。01–30 填涂版的 template.json 没有 write 框，
    # 用它只会产出 0 样本——必须显式用 template_write.json。
    tpl = omr.load_template(open(os.path.join(FIX, 'template_write.json'), encoding='utf-8').read())
    expected = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))['sheets']

    os.makedirs(OUT, exist_ok=True)
    for d in 'ABCD':
        os.makedirs(os.path.join(OUT, d), exist_ok=True)

    files = sorted(f for f in os.listdir(FIX) if f.lower().endswith(IMG_EXT) and f.startswith('第'))
    print(f'[debug] FIX={FIX}')
    print(f'[debug] matching png files: {len(files)}')
    counts = Counter()
    skipped = Counter()          # 提取失败原因（按 sheet）
    manifest = []

    for fn in files:
        # 文件名形如「第01份_张一鸣_01.png」→ key='01'
        key = fn.split('_')[0].replace('第', '').replace('份', '')
        try:
            kn = int(key)
        except ValueError:
            continue
        # 只处理手写版 31–60！01–30 是填涂版：write 框实际为空，且 expected
        # 里存的是其「涂卡答案」，用 template_write.json 坐标去裁会得到气泡/
        # 填涂块的误提字形并以涂卡答案打标 —— 会污染手写训练集，必须排除。
        if not (31 <= kn <= 60):
            continue
        exp = expected.get(key)
        if exp is None:
            print(f'[warn] 真值缺失 {fn} (key={key})，跳过')
            continue
        bgr = imread_cn(os.path.join(FIX, fn))
        quad, _ = omr.detect_marks(bgr, tpl, 0)
        warp, px = omr.warp_page(bgr, quad, tpl)        # 默认 px=8.0，与 decode_write 一致
        _, thr = omr._prep(warp)
        page = tpl['pages'][0]
        for q in page['questions']:
            wb = q.get('write')
            if not wb:
                continue
            truth = exp['answers'].get(str(q['no']))
            if truth is None or truth not in 'ABCD':
                skipped['no_truth'] += 1
                continue
            cx, cy = wb['x'] * px, wb['y'] * px
            rx = max(2.0, wb['w'] * px / 2.0)
            ry = max(2.0, wb['h'] * px / 2.0)
            x0, x1 = max(0, int(round(cx - rx))), int(round(cx + rx)) + 1
            y0, y1 = max(0, int(round(cy - ry))), int(round(cy + ry)) + 1
            box = thr[y0:y1, x0:x1]
            glyph, meta = hwletter.extract_glyph(box)
            if glyph is None:
                skipped[f'{key}_q{q["no"]}({truth})'] += 1
                continue
            idx = counts[truth]
            counts[truth] += 1
            name = f'{key}_{q["no"]:02d}_{truth}_{idx:04d}.png'
            cv2.imencode('.png', glyph)[1].tofile(os.path.join(OUT, truth, name))
            manifest.append({'file': f'{truth}/{name}', 'label': truth,
                            'sheet': key, 'q': q['no']})

    with open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False)

    print('手写样本数:', dict(counts), '合计', sum(counts.values()))
    if skipped:
        print('跳过（extract_glyph 失败）:', dict(skipped))


if __name__ == '__main__':
    main()
