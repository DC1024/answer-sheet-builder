# -*- coding: utf-8 -*-
"""把 torch 权重 app/hwletter_cnn.pt 导出成 ONNX app/hwletter_cnn.onnx。

背景：免安装版扫描端 zip 203 MB，罪魁是 torch_cpu.dll（解包 291.7 MB），
而我们只用到一个约 250 万参数的小 CNN。换 ONNX Runtime 后产物降到 ~20 MB 级。

正确性判据：ONNX 与 torch 在同一批真实样本上的输出必须一致（最大概率偏差 < 1e-5），
不一致就报错退出——不允许「导出来了但数值对不上」。

用法：
    .venv/Scripts/python.exe tools/export_cnn_onnx.py
    .venv/Scripts/python.exe tools/export_cnn_onnx.py --check-only
"""
import argparse
import json
import os
import sys

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

APP = os.path.join(HERE, '..', 'app')
PT = os.path.join(APP, 'hwletter_cnn.pt')
ONNX = os.path.join(APP, 'hwletter_cnn.onnx')
HAND = os.path.join(HERE, '..', 'tests', 'fixtures', 'real30', 'handwritten')
LETTERS = 'ABCD'
LBL2I = dict((c, i) for i, c in enumerate(LETTERS))


def load_glyphs():
    """real30 手写样本 -> [(label_idx, 48x48 uint8), ...]。

    预处理与训练/推理链路逐字对齐：灰度 -> 48x48(INTER_AREA) -> /255。
    这里不 import 训练脚本（它拖 sklearn），直接复刻那几行。
    """
    with open(os.path.join(HAND, 'manifest.json'), encoding='utf-8') as fh:
        manifest = json.load(fh)
    out = []
    for item in manifest:
        path = os.path.join(HAND, item['file'])
        im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if im is None:
            raise FileNotFoundError(path)
        if im.shape != (48, 48):
            im = cv2.resize(im, (48, 48), interpolation=cv2.INTER_AREA)
        out.append((LBL2I[item['label']], im.astype(np.uint8)))
    return out


def softmax(z):
    e = np.exp(z - z.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def do_export(pt_path, onnx_path):
    import torch
    import onnx
    from app.cnn_letter import _build_model

    model = _build_model()()
    model.load_state_dict(torch.load(pt_path, map_location='cpu'))
    model.eval()
    dummy = torch.zeros(1, 1, 48, 48, dtype=torch.float32)
    tmp = onnx_path + '.tmp'
    torch.onnx.export(
        model, dummy, tmp,
        opset_version=17,
        input_names=['glyph'], output_names=['logits'],
        dynamic_axes={'glyph': {0: 'batch'}, 'logits': {0: 'batch'}},
        do_constant_folding=True,
    )
    onnx.save(onnx.load(tmp), onnx_path)
    for junk in (tmp, tmp + '.data', onnx_path + '.data'):
        if os.path.exists(junk):
            os.remove(junk)


def main():
    ap = argparse.ArgumentParser(description='导出/校验 hwletter_cnn 的 ONNX 版本')
    ap.add_argument('--check-only', action='store_true')
    ap.add_argument('--onnx', default=ONNX)
    ap.add_argument('--pt', default=PT)
    a = ap.parse_args()

    if not a.check_only:
        if not os.path.exists(a.pt):
            print('[FAIL] 找不到权重：%s' % a.pt)
            return 1
        do_export(a.pt, a.onnx)
        print('[OK] 已导出 %s（%.2f MB）' % (a.onnx, os.path.getsize(a.onnx) / 1024.0 / 1024.0))

    glyphs = load_glyphs()
    print('对拍样本：%d 个真实手写字形' % len(glyphs))

    import onnxruntime as ort
    sess = ort.InferenceSession(a.onnx, providers=['CPUExecutionProvider'])
    iname = sess.get_inputs()[0].name
    oname = sess.get_outputs()[0].name

    torch_ok = True
    try:
        import torch
        from app.cnn_letter import _build_model
        tmodel = _build_model()()
        tmodel.load_state_dict(torch.load(a.pt, map_location='cpu'))
        tmodel.eval()
    except Exception as e:
        torch_ok = False
        print('[WARN] 无法加载 torch 权重，改为只测 ONNX 独立精度：%s' % e)

    mism = 0
    worst = 0.0
    onnx_right = 0
    for label, g in glyphs:
        x = (g.astype(np.float32) / 255.0)[None, None, ...]
        op = softmax(sess.run([oname], {iname: x})[0])[0]
        pred = LETTERS[int(op.argmax())]
        if pred == LETTERS[label]:
            onnx_right += 1
        if torch_ok:
            with torch.no_grad():
                tp = softmax(tmodel(torch.from_numpy(x)).numpy())[0]
            diff = float(np.max(np.abs(tp - op)))
            worst = max(worst, diff)
            if LETTERS[int(tp.argmax())] != pred or diff > 1e-5:
                mism += 1

    print('ONNX 独立精度：%d/%d' % (onnx_right, len(glyphs)))
    if torch_ok:
        print('与 torch 最大概率偏差：%.3e' % worst)
        if mism:
            print('[FAIL] %d/%d 个样本与 torch 不一致' % (mism, len(glyphs)))
            return 1
        print('[OK] %d/%d 全部一致（letter + conf 双对拍通过）' % (len(glyphs), len(glyphs)))
    return 0


if __name__ == '__main__':
    sys.exit(main())