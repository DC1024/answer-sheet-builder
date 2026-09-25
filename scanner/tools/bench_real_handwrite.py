# -*- coding: utf-8 -*-
"""真实手写 A-D 识别精度基准（bench）。

用途：拿一批**真实学生手写**的扫描件 + 对应阅卷模板 + 真值答案，跑出可复现的
精度结论，供调参前后对比。任何改动 hwletter.py（特征提取 / 打分 / 字形提取）
都应该用它回归一遍 —— 印刷体测不出真实笔迹上的问题（洞收不拢口、断笔、框线）。

用法：
  .venv/Scripts/python.exe tools/bench_real_handwrite.py \
      --img-dir  "<扫描件目录>" \
      --template "<模板.json>" \
      --expected "<真值.json>"

真值格式（与 tests/fixtures/real30/expected.json 一致）：
  {"sheets": {"01": {"name": "张三", "answers": {"1": "A", ...}}, ...}}
扫描件文件名需带序号（如「第01份_张三_01.png」→ key=01）。

输出：
  1. 总体：给出答案的题里判对多少（净准确率）
  2. 混淆矩阵（一眼看出哪个字母在往哪个字母上塌）
  3. flag 分布（ok / faint / doubt / multi / blank）
  4. 「自动阅卷精度 vs 人工复核量」权衡曲线 —— 调 DOUBT_CONF 的依据
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
# 容器内 app 装在 /srv（见 Dockerfile），本地跑则是仓库根 —— 两条路都要能 import
if not os.path.isdir(os.path.join(HERE, '..', 'app')) and os.path.isdir('/srv/app'):
    sys.path.insert(0, '/srv')
from app import omr, hwletter  # noqa: E402

LET = 'ABCD'


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def sheet_key(fn):
    """文件名 → 真值 key：取第一组数字（「第01份_张三_01.png」→ '01'）。"""
    m = re.search(r'\d+', os.path.basename(fn))
    return m.group(0) if m else None


def collect(img_dir, tpl_path, expected):
    """跑全量识别，返回 [(conf, letter, truth, flag)]（conf=None 表示没给答案）。"""
    tpl = omr.load_template(open(tpl_path, encoding='utf-8').read())
    recs = []
    for fn in sorted(glob.glob(os.path.join(img_dir, '*.png'))):
        key = sheet_key(fn)
        exp = expected.get(key)
        if exp is None:
            print(f'[warn] 真值里没有 {os.path.basename(fn)}（key={key}），跳过', file=sys.stderr)
            continue
        bgr = imread_cn(fn)
        quad, _ = omr.detect_marks(bgr, tpl, 0)
        warp, px = omr.warp_page(bgr, quad, tpl)
        _, thr = omr._prep(warp)
        for q in tpl['pages'][0]['questions']:
            wb = q.get('write')
            if not wb:
                continue
            truth = exp['answers'].get(str(q['no']))
            cx, cy = wb['x'] * px, wb['y'] * px
            rx, ry = max(2.0, wb['w'] * px / 2.0), max(2.0, wb['h'] * px / 2.0)
            x0, x1 = max(0, int(round(cx - rx))), int(round(cx + rx)) + 1
            y0, y1 = max(0, int(round(cy - ry))), int(round(cy + ry)) + 1
            r, meta = hwletter.classify_box(thr[y0:y1, x0:x1])
            if r is None:
                recs.append((None, None, truth,
                             'multi' if meta.get('multi') else 'blank'))
            else:
                recs.append((r['conf'], r['letter'], truth, r.get('flag_hint') or 'ok'))
    return recs


def report(recs):
    N = len(recs)
    given = [x for x in recs if x[0] is not None]
    n_ok = sum(1 for c, l, t, f in given if l == t)
    print(f'总题数 {N}｜给出答案 {len(given)}｜判对 {n_ok}')
    print(f'净准确率（给出答案里判对的比例）: {n_ok / max(1, len(given)) * 100:.1f}%')

    print('\n-- flag 分布 --')
    for f, n in Counter(x[3] for x in recs).most_common():
        print(f'  {f:6s}: {n}')

    print('\n-- 混淆矩阵（行=真值，列=识别）--')
    cm = Counter((t, l) for c, l, t, f in given)
    print('        ' + ''.join(f'{x:>6}' for x in LET))
    for w in LET:
        row = [cm[(w, g)] for g in LET]
        print(f'  {w}    ' + ''.join(f'{v:>6}' for v in row) + f'  {sum(row):>5}')
    print('  合计  ' + ''.join(f'{sum(cm[(w, g)] for w in LET):>6}' for g in LET))

    print('\n-- 自动阅卷精度 vs 人工复核量（调 DOUBT_CONF 的依据）--')
    print(f'{"DOUBT_CONF":>10} {"自动判":>8} {"自动准确率":>10} {"存疑":>6} {"没答案":>6} {"人工复核量":>10}')
    for dc in (0.0, 0.3, 0.5, 0.8, 1.0, 1.3, 1.6, 2.0):
        auto = [x for x in recs if x[0] is not None and x[0] >= dc]
        doubt = [x for x in recs if x[0] is not None and x[0] < dc]
        none_ = [x for x in recs if x[0] is None]
        a = sum(1 for c, l, t, f in auto if l == t) / max(1, len(auto))
        print(f'{dc:>10.1f} {len(auto):>8} {a * 100:>9.1f}% {len(doubt):>6} {len(none_):>6} '
              f'{(len(doubt) + len(none_)) / max(1, N) * 100:>9.1f}%')
    return n_ok / max(1, len(given))


def main():
    ap = argparse.ArgumentParser(description='真实手写 A-D 识别精度基准')
    ap.add_argument('--img-dir', required=True, help='手写扫描件目录（*.png）')
    ap.add_argument('--template', required=True, help='阅卷模板 json')
    ap.add_argument('--expected', required=True, help='真值 json')
    ap.add_argument('--fail-under', type=float, default=0.0,
                    help='净准确率低于此值则 exit 1（用于 CI 卡阈值）')
    a = ap.parse_args()

    exp = json.load(open(a.expected, encoding='utf-8'))
    exp = exp.get('sheets', exp)
    recs = collect(a.img_dir, a.template, exp)
    if not recs:
        print('没有可评估的样本', file=sys.stderr)
        sys.exit(2)
    acc = report(recs)
    if acc < a.fail_under:
        print(f'\nFAIL：净准确率 {acc * 100:.1f}% < 阈值 {a.fail_under * 100:.1f}%')
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
