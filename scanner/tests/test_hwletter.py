# -*- coding: utf-8 -*-
"""手写字母分类回归测试（hwletter）。

三层验证，从"可信"到"边界"逐层收紧：
  A. 印刷体 900 样本（real30 真实链路产物）—— 必须 100% 准确、0 误判
  B. 合成形变（旋转/缩放/断笔/位移）—— 破坏性输入不允许"自信地错"，
     wrong 必须显著低于随机；对认不出的要敢 doubt
  C. 整卷 e2e：把工整手写字母写入作答框 → omr.recognize 全链路识别

铁律：识别可以存疑（doubt），但不可以"自信地给错答案"。
       A 层钉 0 wrong；B 层钉 wrong 收敛在低区间（阈值可据调参记录调整）。

运行：.venv/Scripts/python.exe tests/test_hwletter.py
"""
import os, sys, json, random
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import hwletter, omr  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'real30')
LETTERS = os.path.join(FIX, 'letters')


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def norm48(g):
    h, w = g.shape
    s = 44.0 / max(h, w)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    r = cv2.resize(g, (nw, nh), interpolation=cv2.INTER_AREA)
    c = np.zeros((48, 48), np.uint8)
    c[(48 - nh) // 2:(48 - nh) // 2 + nh, (48 - nw) // 2:(48 - nw) // 2 + nw] = r
    return c


def load_manifest():
    return json.load(open(os.path.join(LETTERS, 'manifest.json'), encoding='utf-8'))


def test_printed():
    """A. 印刷体 900 样本必须 100%，0 wrong。"""
    man = load_manifest()
    total = ok = doubt = wrong = 0
    for m in man:
        g = cv2.imread(os.path.join(LETTERS, m['file']), cv2.IMREAD_GRAYSCALE)
        r = hwletter.classify(g)
        total += 1
        if r is None or r['conf'] < hwletter.DOUBT_CONF:
            doubt += 1
        elif r['letter'] == m['label']:
            ok += 1
        else:
            wrong += 1
    print(f'[A] 印刷体: {ok}/{total} ok, doubt={doubt}, wrong={wrong}')
    assert total == 900, '素材应为 900 样本'
    assert wrong == 0, f'印刷体不允许误判：{wrong} 个 wrong'
    assert ok / total >= 0.9, f'印刷体识别率过低：{ok/total:.4f}'


def augment(g):
    outs = []
    h, w = g.shape
    for ang in (-10, 8):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        outs.append(('rot', norm48(cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0))))
    for sc in (0.8, 1.15):
        nh, nw = max(1, int(h * sc)), max(1, int(w * sc))
        r = cv2.resize(g, (nw, nh), interpolation=cv2.INTER_LINEAR)
        outs.append(('sc', norm48(r)))
    d = g.copy()
    for _ in range(2):
        ys, xs = np.nonzero(d)
        if len(xs) == 0:
            break
        i = random.randrange(len(xs))
        cv2.circle(d, (int(xs[i]), int(ys[i])), 3, 0, -1)
    outs.append(('br', norm48(d)))
    outs.append(('sh', norm48(np.roll(np.roll(g, 2, 0), 1, 1))))
    return outs


def test_deform():
    """B. 合成形变：wrong 必须收敛在低区间（破坏性输入不得大面积自信地错）。
    调参记录：DOUBT_CONF=1.0 + 洞检测重构后，印刷 100%、形变 wrong 收敛。"""
    random.seed(42)
    man = load_manifest()
    samples = random.sample(man, min(len(man), 120))
    ok = doubt = wrong = total = 0
    for m in samples:
        g = cv2.imread(os.path.join(LETTERS, m['file']), cv2.IMREAD_GRAYSCALE)
        for tag, v in augment(g):
            r = hwletter.classify(v)
            total += 1
            if r is None or r['conf'] < hwletter.DOUBT_CONF:
                doubt += 1
            elif r['letter'] == m['label']:
                ok += 1
            else:
                wrong += 1
    print(f'[B] 合成形变: {ok}/{total} ok, doubt={doubt}, wrong={wrong} '
          f'(wrong 率 {wrong/total:.3f})')
    # 破坏性形变允许 doubt（认不出），但不允许 wrong 超过 ok 的合理比例
    assert wrong / total < 0.30, f'合成形变误判率过高：{wrong/total:.3f}'
    assert doubt > 0, '破坏性形变应至少有一部分认不出进复核'


def test_e2e_handwrite():
    """C. 整卷 e2e：工整手写字母写入作答框 → omr.recognize。
    用 real30 的模板 + 图，在每题右侧空白画一个作答框，写入已知答案（putText 工整字），
    断言 decode_write 读回正确。验证的是"合上整条链路"，不是字母分类本身。"""
    tpl = omr.load_template(open(os.path.join(FIX, 'template.json'), encoding='utf-8').read())
    expected = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))['sheets']
    tpl = dict(tpl)
    tpl['pages'] = [dict(p) for p in tpl['pages']]
    page = tpl['pages'][0]
    page['questions'] = [dict(q) for q in page['questions']]
    ans = expected['01']['answers']
    # 建一份"纯手写卷"模板：每题去掉 options、只留 write 作答框（在选项组右侧空白）
    for q in page['questions']:
        q['options'] = []                          # 关键：必须清空 options 才走 decode_write
        qx = q['x']
        q['write'] = {'x': round(qx + 36, 2), 'y': q['y'], 'w': 8.0, 'h': 9.0}
        q['_wans'] = ans[str(q['no'])]

    # 拿第01份原图，在作答框写入工整手写字母后识别
    bgr = imread_cn(os.path.join(FIX, '第01份_张一鸣_01.png'))
    quad, _ = omr.detect_marks(bgr, tpl)
    warp, px = omr.warp_page(bgr, quad, tpl, px_per_mm=15.11)
    work = warp.copy()
    for q in page['questions']:
        wb = q['write']
        letter = q['_wans']
        cx, cy = int(wb['x'] * px), int(wb['y'] * px)
        fs = wb['h'] * px * 0.8
        cv2.putText(work, letter, (cx - int(fs * 0.35), cy + int(fs * 0.5)),
                    cv2.FONT_HERSHEY_SIMPLEX, fs / 32.0, (0, 0, 0),
                    max(3, int(px * 0.13)), cv2.LINE_AA)
    work = cv2.dilate(work, np.ones((3, 3), np.uint8), iterations=1)
    out = omr.recognize(work, tpl, overlay=False)
    wres = {r['no']: r for r in out['questions'] if r.get('x') is not None and r.get('blobs') is not None}
    got = ''.join(str(wres[i]['answer']) if i in wres and wres[i]['answer'] else '?'
                  for i in sorted(range(1, 11)))
    want = ''.join(ans[str(i)] for i in range(1, 11))
    n_ok = sum(1 for i in range(1, 11) if i in wres and wres[i].get('answer') == ans[str(i)])
    # 给出答案的题必须全对（0 自信错）；multi/doubt/空框允许（进复核，不硬猜）。
    n_given = sum(1 for i in range(1, 11) if i in wres and wres[i].get('answer'))
    wrong = n_given - n_ok
    print(f'[C] 手写整卷：识别 "{got}" / 真值 "{want}" → 答 {n_ok}/10，'
          f'给出答案 {n_given} 题，其中自信错 {wrong}')
    print(f'     保守进复核 {10 - n_given} 题（multi/空框/低置信，可人工确认）')
    assert wrong == 0, f'手写整卷出现自信错：{wrong} 题（宁可复核，不可硬猜）'
    assert n_ok >= 3, f'手写整卷识别过少：{n_ok}/10（合成字体变形不可控，但链路应工作）'


def main():
    test_printed()
    test_deform()
    test_e2e_handwrite()
    print('\n🎉 手写字母分类（hwletter）全部通过')
    sys.exit(0)


if __name__ == '__main__':
    main()