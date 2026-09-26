# -*- coding: utf-8 -*-
"""CNN 接入生产线后的回归验证：用真实手写卷（31-60）跑**完整 omr.recognize 路径**，
对比 CNN 一选 + OpenCV 交叉验证 与 纯 OpenCV 老路径，对 expected.json 真值。

跑的是生产代码（omr.recognize → decode_write），不是 bench 里那条并行复刻，
所以能真正验证"接进去了没"以及"接进去后有没有破坏老行为"。

用法：
  .venv/Scripts/python.exe tools/verify_cnn_integration.py
"""
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
from app import omr  # noqa: E402

IMG_DIR = os.path.join(HERE, '..', 'tests', 'fixtures', 'real30')
TPL = os.path.join(IMG_DIR, 'template_write.json')
EXPECTED = os.path.join(IMG_DIR, 'expected.json')
LET = 'ABCD'

# 只在 31-60（真实手写）上评；01-30 是涂卡，不含 write 框
KEY_RE = re.compile(r'第(\d+)份')


def sheet_key(fn):
    m = KEY_RE.search(os.path.basename(fn))
    return int(m.group(1)) if m else None


def run(mode):
    """mode: 'cnn'（omr.recognize 传 cnn_model）或 'opencv'（纯 OpenCV）。

    返回 recs: [(letter_or_None, flag, truth_or_None, conf)]，只统计 31-60 手写卷。
    """
    tpl = omr.load_template(open(TPL, encoding='utf-8').read())
    exp = json.load(open(EXPECTED, encoding='utf-8'))
    exp = exp.get('sheets', exp)
    cnn_model = None
    if mode == 'cnn':
        from app import cnn_letter
        cnn_model = cnn_letter.load_model()

    recs = []
    for fn in sorted(glob.glob(os.path.join(IMG_DIR, '*.png'))):
        k = sheet_key(fn)
        if k is None or not (31 <= k <= 60):
            continue
        key = f'{k:02d}'
        sheet = exp.get(key)
        if sheet is None:
            continue
        bgr = cv2.imdecode(np.fromfile(fn, dtype=np.uint8), cv2.IMREAD_COLOR)
        out = omr.recognize(bgr, tpl, cnn_model=cnn_model if mode == 'cnn' else None)
        writes = {w['no']: w for w in out['questions'] if 'answer' in w and w.get('no') is not None
                  and any(q.get('write') for q in tpl['pages'][0]['questions'] if q['no'] == w['no'])}
        # 只收 write 题（手写框），靠模板标注区分
        for q in tpl['pages'][0]['questions']:
            if not q.get('write'):
                continue
            w = writes.get(q['no'])
            if w is None:
                continue
            truth = sheet['answers'].get(str(q['no']))
            recs.append((w.get('answer'), w.get('flag'), truth, w.get('best')))
    return recs


def report(mode, recs):
    N = len(recs)
    given = [r for r in recs if r[0] is not None]
    n_ok = sum(1 for a, f, t, c in given if a == t)
    auto = [r for r in recs if r[0] is not None and r[1] == 'ok']
    n_auto_ok = sum(1 for a, f, t, c in auto if a == t)
    review = [r for r in recs if r[1] in ('review', 'doubt', 'faint', 'multi', 'blank')]
    print(f'\n===== {mode.upper()} 路径（31-60 手写，{N} 题）=====')
    print(f'净准确率（给出答案里判对）: {n_ok}/{len(given)} = {n_ok / max(1, len(given)) * 100:.1f}%')
    print(f'ok 自动判（flag=ok 且给答案）: {n_auto_ok}/{len(auto)} = '
          f'{n_auto_ok / max(1, len(auto)) * 100:.1f}%')
    print(f'进复核队列: {len(review)}/{N} = {len(review) / max(1, N) * 100:.1f}%')
    print('flag 分布:', dict(Counter(f for a, f, t, c in recs)))
    print('混淆矩阵（行=真值 列=识别）:')
    cm = Counter((t, a) for a, f, t, c in given)
    print('        ' + ''.join(f'{x:>6}' for x in LET))
    for w in LET:
        row = [cm[(w, g)] for g in LET]
        print(f'  {w}    ' + ''.join(f'{v:>6}' for v in row) + f'  {sum(row):>5}')
    return n_ok / max(1, len(given))


if __name__ == '__main__':
    r_oc = run('opencv')
    acc_oc = report('opencv', r_oc)
    r_cnn = run('cnn')
    acc_cnn = report('cnn', r_cnn)
    print('\n===== 小结 =====')
    print(f'纯 OpenCV 净准确率: {acc_oc * 100:.1f}%')
    print(f'CNN 一选+OpenCV校验 净准确率: {acc_cnn * 100:.1f}%')
