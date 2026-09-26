# -*- coding: utf-8 -*-
"""CNN 手写 A-D 分类器（SmallCNN）。作为线上 decode_write 的**一选**分类器，
OpenCV hwletter 退为二选 / 交叉验证；二者不一致或 CNN 置信过低 → 标 review/doubt
进复核队列。

权重文件：hwletter_cnn.pt（state_dict），部署时把它放到本模块同目录（/srv/app/）。

设计要点：本模块**顶部不导入 torch**——只在 load_model / classify 真正被调用时才 import，
这样没装 torch 的部署（容器）导入 app 包、调用 decode_write(cnn_model=None) 时不会崩，
自动退回纯 OpenCV 行为。
"""
import os

LET = ['A', 'B', 'C', 'D']
LBL2I = {c: i for i, c in enumerate(LET)}
I2LBL = {i: c for c, i in LBL2I.items()}
CNN_THRESH = 0.70  # CNN 置信低于此 → 标 doubt（进复核）

DEFAULT_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hwletter_cnn.pt')


def _build_model():
    import torch
    import torch.nn as nn

    class SmallCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
                nn.Conv2d(32, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
                nn.MaxPool2d(2),
                nn.Dropout(0.25),
                nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
                nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
                nn.MaxPool2d(2),
                nn.Dropout(0.25),
            )
            self.classifier = nn.Sequential(
                nn.Linear(64 * 12 * 12, 256), nn.ReLU(), nn.Dropout(0.5),
                nn.Linear(256, 4),
            )

        def forward(self, x):
            x = self.features(x)
            x = x.view(x.size(0), -1)
            return self.classifier(x)

    return SmallCNN


def load_model(path=DEFAULT_MODEL):
    """加载权重 → 返回处于 eval 模式的模型对象。找不到权重 / 无 torch 时抛异常。"""
    import torch
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    SmallCNN = _build_model()
    model = SmallCNN()
    state = torch.load(path, map_location='cpu')
    model.load_state_dict(state)
    model.eval()
    return model


def classify_glyph(glyph_u8, model):
    """glyph_u8: 48x48 uint8 {0,255}（墨=255）。返回 (letter, conf[0..1])。"""
    import numpy as np
    import torch
    import torch.nn.functional as F
    x = glyph_u8.astype(np.float32) / 255.0          # 墨 → 1.0
    x = x[None, None, ...]                            # 1,1,48,48
    with torch.no_grad():
        out = model(torch.from_numpy(x))
        prob = F.softmax(out, dim=1)
        conf, pred = prob.max(dim=1)
    return I2LBL[int(pred)], float(conf)


def classify_box(box_thr, model):
    """作答框二值图 → (letter, conf) 或 (None, 0.0)（空框）。复用 hwletter 提字形。"""
    from . import hwletter
    glyph, _ = hwletter.extract_glyph(box_thr)
    if glyph is None:
        return None, 0.0
    return classify_glyph(glyph, model)
