# 单图诊断：把定位点检测 / 矫正 / 采样 / 判定的中间结果全部打出来，用于调参与排查。
#
#   python tests/diag1.py                        # 用仓库自带素材 s01.png
#   python tests/diag1.py /path/to/真实扫描.png   # 用你自己的扫描件
#
# 产物（diag_warp.png / diag_overlay.png）默认写到系统临时目录，不污染仓库。
import json
import os
import sys
import tempfile

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app import omr      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures')
OUT = tempfile.mkdtemp(prefix='asb-omr-diag-')

img_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(FIX, 's01.png')
TPL = omr.load_template(open(os.path.join(FIX, 'template.json'), encoding='utf-8').read())

img = cv2.imread(img_path)
if img is None:
    sys.exit(f'读不到图片：{img_path}')
print('image:', img.shape, '| paper:', TPL['paper'], '| marks:', TPL['marks'])

quad, diag = omr.detect_marks(img, TPL)
print('quad(图像坐标):', quad.tolist())
print('diag:', diag)

warp, px = omr.warp_page(img, quad, TPL, 8.0)
print('warp:', warp.shape, '->', os.path.join(OUT, 'diag_warp.png'))
cv2.imwrite(os.path.join(OUT, 'diag_warp.png'), warp)

page = TPL['pages'][0]
sampled = omr.sample_bubbles(warp, page, px)
r = omr.decide(sampled)

# 关键量：ratio(二值深色占比) 与 ink(灰度墨迹均值)，两者一起看才判断得出阈值该定在哪
print('\n题号  判定  标记    best  second   各选项 ink')
for q in r:
    inks = ' '.join(f'{k}={v:.3f}' for k, v in sorted(q['inks'].items()))
    print(f"{q['no']:>4}  {str(q['answer']):>4}  {q['flag']:<6} {q['best']:.3f} {q['second']:.3f}   {inks}")

ov = omr.draw_overlay(warp, sampled, r, px)
cv2.imwrite(os.path.join(OUT, 'diag_overlay.png'), ov)
print('\n校对图 ->', os.path.join(OUT, 'diag_overlay.png'))
