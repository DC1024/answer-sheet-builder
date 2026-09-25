# -*- coding: utf-8 -*-
"""真实答题卡回归测试（real30）：30 张实际扫描件 × 逆向模板，全量识别必须与真值一致。

这批素材的意义：此前结构分类与判定阈值全部靠合成图调参 —— 真实笔迹/真实印扫链路上
第一次有了可重复的验证基准。任何改动 omr.py 采样、判定、矫正逻辑的提交都必须跑过它。

运行：.venv/Scripts/python.exe tests/test_real30.py   （脚本式测试，失败 sys.exit(1)）
"""
import os
import sys

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import omr  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'real30')


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    tpl = omr.load_template(open(os.path.join(FIX, 'template.json'), encoding='utf-8').read())
    expected = __import__('json').load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))

    files = sorted(f for f in os.listdir(FIX) if f.endswith('.png'))
    assert len(files) == 30, f'素材应为 30 张，实际 {len(files)}'
    assert len(expected['sheets']) == 30, 'expected.json 应有 30 名学生'

    failures = []
    n_ans = 0
    for fn in files:
        key = fn.split('_')[0].replace('第', '').replace('份', '')
        exp = expected['sheets'].get(key)
        if exp is None:
            failures.append(f'{fn}: expected.json 缺少学生 {key}')
            continue
        try:
            out = omr.recognize(imread_cn(os.path.join(FIX, fn)), tpl, overlay=False)
        except omr.OmrError as e:
            failures.append(f'{fn}: 识别异常 {e}')
            continue
        assert out['sid'] is None, f'{fn}: 本批卷面无考号填涂区，sid 应为 None'
        for r in out['questions']:
            no = str(r['no'])
            want = exp['answers'][no]
            got = r['answer']
            n_ans += 1
            if got != want:
                failures.append(f'{fn}: 题{no} 识别 {got} / 真值 {want} (flag={r["flag"]})')
            elif r['flag'] != 'ok':
                failures.append(f'{fn}: 题{no}={want} 但 flag={r["flag"]}（应为干净识别）')

    total = 30 * 10
    if failures:
        print(f'FAIL：{len(failures)} 处不一致（共 {total} 个判定点）')
        for f in failures[:20]:
            print(' -', f)
        sys.exit(1)
    print(f'OK：30 张真实扫描件 × 10 题 = {total} 个判定点全部与真值一致，flag 全部 ok')
    sys.exit(0)


if __name__ == '__main__':
    main()
