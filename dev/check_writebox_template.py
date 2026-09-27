# 端到端验证（第 2 步，扫描端）：把制卡端导出的 writebox 模板喂给 omr，
# 在 write 框坐标上亲手写一遍，验证 decode_write 链路真的认得出来。
#
# 第 1 步（制卡端渲染 + 导出模板）在 dev/verify_writebox.cjs。
# **为什么不合成一个脚本**：本机沙箱里 node 起不了任何子进程（execFileSync 连 cmd.exe 都
# EBUSY），「node 内部顺便调 Python」在沙箱里只会得到一个看起来跑了、其实没跑的假绿。
# 两步分开，各自都是真执行。
#
# 用法：
#   python -m http.server 8080                       # 仓库根目录起静态服务
#   NODE_PATH=<node_modules> node dev/verify_writebox.cjs
#   scanner/.venv/Scripts/python.exe dev/check_writebox_template.py
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scanner'))

import cv2                                                                     # noqa: E402
import numpy as np                                                             # noqa: E402

from app import omr                                                            # noqa: E402

# 模板在 dev/.cache（第 1 步写的产物）；真实扫描件在 scanner/tests/fixtures/real30
TPL = os.path.join(HERE, '.cache', 'writebox', 'builder_writebox_template.json')
FIX = os.path.join(ROOT, 'scanner', 'tests', 'fixtures', 'real30')
SHEET = os.path.join(FIX, '第01份_张一鸣_01.png')

FAILS = []


def ok(cond, label, extra=''):
    print(('  \u2705 ' if cond else '  \u274c ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


if not os.path.exists(TPL):
    print(f'找不到模板 {TPL}\n先跑第 1 步：NODE_PATH=<node_modules> node dev/verify_writebox.cjs')
    sys.exit(2)

print('=== 扫描端 decode_write 链路（builder 模板）===')
with open(TPL, encoding='utf-8') as f:
    tpl = omr.load_template(json.dumps(json.load(f)))

n_write = sum(1 for p in tpl['pages'] for q in p.get('questions', []) if q.get('write'))
print(f'  format {tpl["format"]}，write 题 {n_write}')
ok(n_write == 6, '模板里 6 道 write 题（load_template 认这些字段）', f'实测 {n_write}')

# 在 write 框坐标上"手写"一遍，走完整条识别链路
ANSWERS = 'ADBDDACACA'
bgr = cv2.imdecode(np.fromfile(SHEET, dtype=np.uint8), cv2.IMREAD_COLOR)
quad, _ = omr.detect_marks(bgr, tpl)
warp, px = omr.warp_page(bgr, quad, tpl, px_per_mm=15.11)
work = warp.copy()
for q in [q for p in tpl['pages'] for q in p.get('questions', []) if q.get('write')]:
    w = q['write']
    cx, cy = int(w['x'] * px), int(w['y'] * px)
    fs = w['h'] * px * 0.8
    cv2.putText(work, ANSWERS[q['no'] - 1], (cx - int(fs * 0.35), cy + int(fs * 0.5)),
                cv2.FONT_HERSHEY_SIMPLEX, fs / 32.0, (0, 0, 0),
                max(3, int(px * 0.13)), cv2.LINE_AA)
work = cv2.dilate(work, np.ones((3, 3), np.uint8), iterations=1)

out = omr.recognize(work, tpl, overlay=False)
wres = {r['no']: r for r in out['questions'] if r.get('x') is not None}
got = ''.join(str(wres[i]['answer']) if i in wres and wres[i]['answer'] else '?'
              for i in range(1, 7))
n_ok = sum(1 for i in range(1, 7)
           if i in wres and wres[i].get('answer') == ANSWERS[i - 1])
conf_wrong = sum(1 for i in range(1, 7)
                 if i in wres and wres[i].get('answer')
                 and wres[i]['answer'] != ANSWERS[i - 1])
print(f'  识别结果 {got} / 真值 {ANSWERS[:6]}')
print(f'  正确 {n_ok}/6，自信错 {conf_wrong}')
ok(n_ok >= 3, 'builder 模板手写链路能识别（≥3/6）', f'实测 {n_ok}/6')

print()
if FAILS:
    print(f'\u274c {len(FAILS)} 项失败')
    sys.exit(1)
print('\U0001f389 扫描端 decode_write 链路 全部通过')
