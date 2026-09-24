"""测试共用：素材路径与手机拍照模拟。

手机拍照模拟（透视 + 明暗渐变 + 模糊 + 噪声 + JPEG）由测试运行时现场合成，
产物写进临时目录，不污染 tests/fixtures/。
"""
import os
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures')          # 仓库内、已提交的素材
TMP = tempfile.mkdtemp(prefix='asb-omr-test-')


def photo_sim(src, dst, seed=0, quality=82):
    """模拟手机拍照：随机透视 + 明暗渐变 + 高斯模糊 + 噪声 + JPEG 压缩"""
    rng = np.random.default_rng(seed)
    img = cv2.imread(src)
    if img is None:
        raise FileNotFoundError(src)
    h, w = img.shape[:2]
    amp = 0.05
    src_pts = np.float32([[amp * w * rng.uniform(0, 1), amp * h * rng.uniform(0, 1)],
                          [w - amp * w * rng.uniform(0, 1), amp * h * rng.uniform(0, 1)],
                          [w - amp * w * rng.uniform(0, 1), h - amp * h * rng.uniform(0, 1)],
                          [amp * w * rng.uniform(0, 1), h - amp * h * rng.uniform(0, 1)]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), src_pts)
    big = cv2.warpPerspective(img, M, (int(w * 1.12), int(h * 1.12)), borderValue=(235, 232, 228))
    bh, bw = big.shape[:2]
    # 明暗渐变（左上亮右下暗）
    gx = np.linspace(1.0, 0.72, bw, dtype=np.float32)
    gy = np.linspace(1.0, 0.80, bh, dtype=np.float32)
    light = np.clip(np.outer(gy, gx), 0.55, 1.0)[..., None]
    big = np.clip(big.astype(np.float32) * light + rng.normal(0, 4, big.shape), 0, 255).astype(np.uint8)
    big = cv2.GaussianBlur(big, (3, 3), 0)
    ok, buf = cv2.imencode('.jpg', big, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    with open(dst, 'wb') as f:
        f.write(buf.tobytes())
    return dst


def phone_variants(names):
    """把 fixtures 里的若干张 PNG 各合成一张手机拍照图，返回 (文件名, 绝对路径) 列表"""
    out = []
    for n in names:
        dst = os.path.join(TMP, os.path.splitext(n)[0] + '_phone.jpg')
        photo_sim(os.path.join(FIX, n), dst, seed=abs(hash(n)) % 1000)
        out.append((os.path.basename(dst), dst))
    return out
