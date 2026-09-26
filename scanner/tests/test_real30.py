# -*- coding: utf-8 -*-
"""真实答题卡回归测试（real30）：30 张实际扫描件 × 逆向模板，识别必须与真值逐题一致。

这批素材的意义：此前结构分类与判定阈值全部靠合成图调参 —— 真实印扫链路上第一次有了
可重复的验证基准。任何改动 omr.py 采样、判定、矫正逻辑的提交都必须跑过它。

素材目录后来多了一批东西：`第31–60份_*` 是**手写版**卷子，配的是 `template_write.json`
（作答区是手写框，不是填涂圈），它们是那份 CNN 的训练/评测素材。**它们不属于这条回归** ——
拿填涂模板去采样手写框只会得到一片 blank/faint，那是「量的地方不对」，不是识别退步。
手写版由 `tests/test_hwletter.py` 与 `tools/bench_real_handwrite.py` 负责。

所以这里**不写死张数**，而是按 `expected.json` 里的 `printedMax` 切分：

    * ≤ printedMax  → 本测试负责，逐题逐点断言（真值必须齐 1–10 题，缺一题就算失败）
    * > printedMax  → 只报一句「这些是手写版，不在这里量」，不判失败

（历史上这里是 `assert len(files) == 30`，加了手写版素材之后它就变成一条跟识别毫无关系的
假失败 —— 所以改成按模板切分。）

运行：.venv/Scripts/python.exe tests/test_real30.py   （脚本式测试，失败 sys.exit(1)）
"""
import json
import os
import sys

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import omr  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'real30')
QUESTIONS = [str(i) for i in range(1, 11)]


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    tpl = omr.load_template(open(os.path.join(FIX, 'template.json'), encoding='utf-8').read())
    expected = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))
    sheets = expected['sheets']
    # 缺省 = 全部：万一 printedMax 忘了写，宁可全量断言，也不要悄悄少测一批。
    printed_max = int(expected.get('printedMax', max(int(k) for k in sheets)))

    by_key = {f.split('_')[0].replace('第', '').replace('份', ''): f
              for f in os.listdir(FIX) if f.endswith('.png')}

    keys = sorted((k for k in sheets if int(k) <= printed_max), key=int)
    handwritten = sorted((k for k in sheets if int(k) > printed_max), key=int)

    missing = [k for k in keys if k not in by_key]
    if missing:
        print(f'FAIL：这些学生在 expected.json 里有真值，但目录里没有对应扫描件：{missing}')
        sys.exit(1)

    holes = []
    for k in keys:
        ans = sheets[k].get('answers') or {}
        gap = [q for q in QUESTIONS if q not in ans]
        if gap:
            holes.append(f'{k} {sheets[k].get("name", "")} 缺题 {gap}')
    if holes:
        print('FAIL：填涂版这批的真值必须齐 1–10 题（缺题会让判定点悄悄变少）：')
        for h in holes:
            print(' -', h)
        sys.exit(1)

    total = len(keys) * len(QUESTIONS)
    failures = []
    n_ans = 0
    for key in keys:
        fn = by_key[key]
        exp = sheets[key]['answers']
        try:
            out = omr.recognize(imread_cn(os.path.join(FIX, fn)), tpl, overlay=False)
        except omr.OmrError as e:
            failures.append(f'{fn}: 识别异常 {e}')
            continue
        assert out['sid'] is None, f'{fn}: 本批卷面无考号填涂区，sid 应为 None'
        for r in out['questions']:
            no = str(r['no'])
            want = exp[no]
            got = r['answer']
            n_ans += 1
            if got != want:
                failures.append(f'{fn}: 题{no} 识别 {got} / 真值 {want} (flag={r["flag"]})')
            elif r['flag'] != 'ok':
                failures.append(f'{fn}: 题{no}={want} 但 flag={r["flag"]}（应为干净识别）')

    if failures:
        print(f'FAIL：{len(failures)} 处不一致（{len(keys)} 张填涂版，{total} 个判定点）')
        for f in failures[:20]:
            print(' -', f)
        sys.exit(1)
    if n_ans != total:
        print(f'FAIL：只判了 {n_ans} 个点，应为 {total} —— 卷面题数与模板对不上。')
        sys.exit(1)

    print(f'OK：{len(keys)} 张真实扫描件 × {len(QUESTIONS)} 题 = {total} 个判定点全部与真值一致，flag 全部 ok')
    if handwritten:
        print(f'    （目录里另有 {len(handwritten)} 张手写版，配 template_write.json，不在本测试范围 —— '
              f'见 tests/test_hwletter.py 与 tools/bench_real_handwrite.py）')
    sys.exit(0)


if __name__ == '__main__':
    main()
