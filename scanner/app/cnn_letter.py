# -*- coding: utf-8 -*-
"""手写 A-D 分类器（CNN）。

推理后端可以是 **ONNX Runtime** 或 **PyTorch**，对外 API 完全一致：
`load_model()` 返回一个 `.predict(glyph_u8) -> (letter, conf)` 的包装对象，
`classify_glyph` / `classify_box` 不关心后端是哪一个。

为什么要有两套后端
----------------
- **ONNX Runtime（首选）**：体积小、冷启快，不需 libtorch（291 MB 的 torch_cpu.dll）。
  权重 `hwletter_cnn.onnx`（约 9 MB），用 `tools/export_cnn_onnx.py` 从 `.pt` 导出，
  已与 torch 在真实样本上逐一比对、数值一致。
- **PyTorch（兜底）**：历史权重 `hwletter_cnn.pt`，以及没有 onnxruntime 的环境。
  完全兼容旧部署与训练链路。

降级原则不变：本模块**顶部不 import torch / onnxruntime** —— 只在被真正调用、
  且对应库存在时才 import；两库都没有 / 没有权重时 `load_model` 抛异常，
  由调用方（server._get_cnn_model）捕获后退回纯 OpenCV，服务照常起。

环境变量：
  ASB_CNN_MODEL  显式指定权重路径（.onnx 或 .pt 皆可）；指到一个不存在的路径 = 显式关掉 CNN。
"""
import importlib.util as _util
import os

LET = ['A', 'B', 'C', 'D']
LBL2I = {c: i for i, c in enumerate(LET)}
I2LBL = {i: c for c, i in LBL2I.items()}
CNN_THRESH = 0.70  # CNN 置信低于此 -> 标 doubt（进复核）

_DIR = os.path.dirname(os.path.abspath(__file__))
PT_MODEL = os.path.join(_DIR, 'hwletter_cnn.pt')
ONNX_MODEL = os.path.join(_DIR, 'hwletter_cnn.onnx')

# 向后兼容：server / 训练脚本仍引用 DEFAULT_MODEL，语义保持「默认权重路径」。
DEFAULT_MODEL = PT_MODEL


def _have(module):
    try:
        return _util.find_spec(module) is not None
    except Exception:  # noqa: BLE001
        return False


def have_onnxruntime():
    return _have('onnxruntime')


def have_torch():
    return _have('torch')


def default_model_path():
    """自动选权重：优先 ONNX（若 onnxruntime 可用 + .onnx 存在），否则 .pt。

    ASB_CNN_MODEL 一旦显式给出就直接用它（保持手动覆盖语义）。
    """
    env = os.environ.get('ASB_CNN_MODEL')
    if env:
        return env
    if have_onnxruntime() and os.path.isfile(ONNX_MODEL):
        return ONNX_MODEL
    return PT_MODEL


def _build_model():
    """构造 SmallCNN 类（torch 后端用）。导入 torch 前不要调用。"""
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


class _OnnxModel:
    """ONNX Runtime 后端包装。predict(glyph_u8) -> (letter, conf)。"""

    kind = 'onnx'

    def __init__(self, path, session):
        self.path = path
        self.session = session
        self.input_name = session.get_inputs()[0].name
        self.output_name = session.get_outputs()[0].name

    @staticmethod
    def _softmax(z):
        np = __import__('numpy')
        e = np.exp(z - z.max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True)

    def predict(self, glyph_u8):
        import numpy as np
        x = glyph_u8.astype(np.float32) / 255.0
        x = x[None, None, ...]
        out = self.session.run([self.output_name], {self.input_name: x})[0]
        prob = self._softmax(out)
        conf, pred = prob[0].max(), prob[0].argmax()
        return I2LBL[int(pred)], float(conf)


class _TorchModel:
    """PyTorch 后端包装。predict(glyph_u8) -> (letter, conf)。"""

    kind = 'torch'

    def __init__(self, path, model):
        self.path = path
        self.model = model

    def predict(self, glyph_u8):
        import numpy as np
        import torch
        import torch.nn.functional as F
        x = glyph_u8.astype(np.float32) / 255.0
        x = x[None, None, ...]
        with torch.no_grad():
            out = self.model(torch.from_numpy(x))
            prob = F.softmax(out, dim=1)
            conf, pred = prob.max(dim=1)
        return I2LBL[int(pred)], float(conf)


def load_model(path=None):
    """加载权重 -> 返回 `.predict` 包装对象（kind='onnx'/'torch'）。

    找不到权重 / 两个后端库都不在时抛异常（调用方据此退回纯 OpenCV）。
    path 省略时走 default_model_path()：优先 ONNX。
    """
    if not path:
        path = default_model_path()
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    # 给了 .pt 也先看同目录有没有 .onnx + onnxruntime，有就优先（体积/冷启更优）
    base = path[:-3] if path.lower().endswith('.pt') else None
    onnx_candidate = (base + '.onnx') if base else path
    if onnx_candidate.endswith('.onnx') and have_onnxruntime():
        import onnxruntime as ort
        sess = ort.InferenceSession(onnx_candidate, providers=['CPUExecutionProvider'])
        return _OnnxModel(onnx_candidate, sess)

    # 否则走 torch
    import torch
    SmallCNN = _build_model()
    model = SmallCNN()
    model.load_state_dict(torch.load(path, map_location='cpu'))
    model.eval()
    return _TorchModel(path, model)


def classify_glyph(glyph_u8, model):
    """glyph_u8: 48x48 uint8 {0,255}（墨=255）。返回 (letter, conf[0..1])。"""
    return model.predict(glyph_u8)


def classify_box(box_thr, model):
    """作答框二值图 -> (letter, conf) 或 (None, 0.0)（空框）。复用 hwletter 提字形。"""
    from . import hwletter
    glyph, _ = hwletter.extract_glyph(box_thr)
    if glyph is None:
        return None, 0.0
    return classify_glyph(glyph, model)
