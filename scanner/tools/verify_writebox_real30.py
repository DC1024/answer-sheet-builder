# -*- coding: utf-8 -*-
"""服务器容器内验证：用 real30 真实模板+真实扫描件，验证部署的 writebox 手写识别链路。
等价于本地 test_hwletter.py 的 C 层（test_e2e_handwrite）。
素材在 /tmp/real30/ 下（由部署者上传：template.json / 第01份_张一鸣_01.png / expected.json）。
用法（容器内）：python -c "..." 或本文件。
"""
import os, sys, json
import numpy as np
import cv2

sys.path.insert(0, "/srv")
from app import omr, hwletter  # noqa: E402

FIX = "/tmp/real30"

def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

def test_e2e_handwrite():
    print("== 整卷手写链路（real30 模板 + 真实扫描件 + write 作答框） ==")
    tpl = omr.load_template(open(os.path.join(FIX, "template.json"), encoding="utf-8").read())
    expected = json.load(open(os.path.join(FIX, "expected.json"), encoding="utf-8"))["sheets"]
    tpl = dict(tpl)
    tpl["pages"] = [dict(p) for p in tpl["pages"]]
    page = tpl["pages"][0]
    page["questions"] = [dict(q) for q in page["questions"]]
    ans = expected["01"]["answers"]
    for q in page["questions"]:
        q["options"] = []                      # 关键：清空 options 才走 decode_write
        qx = q["x"]
        q["write"] = {"x": round(qx + 36, 2), "y": q["y"], "w": 8.0, "h": 9.0}
        q["_wans"] = ans[str(q["no"])]

    bgr = imread_cn(os.path.join(FIX, "第01份_张一鸣_01.png"))
    quad, _ = omr.detect_marks(bgr, tpl)
    warp, px = omr.warp_page(bgr, quad, tpl, px_per_mm=15.11)
    work = warp.copy()
    for q in page["questions"]:
        wb = q["write"]
        letter = q["_wans"]
        cx, cy = int(wb["x"] * px), int(wb["y"] * px)
        fs = wb["h"] * px * 0.8
        cv2.putText(work, letter, (cx - int(fs * 0.35), cy + int(fs * 0.5)),
                    cv2.FONT_HERSHEY_SIMPLEX, fs / 32.0, (0, 0, 0),
                    max(3, int(px * 0.13)), cv2.LINE_AA)
    work = cv2.dilate(work, np.ones((3, 3), np.uint8), iterations=1)
    out = omr.recognize(work, tpl, overlay=False)
    wres = {r["no"]: r for r in out["questions"] if r.get("blobs") is not None}
    got = "".join(str(wres[i]["answer"]) if i in wres and wres[i]["answer"] else "?"
                  for i in sorted(range(1, 11)))
    want = "".join(ans[str(i)] for i in range(1, 11))
    n_ok = sum(1 for i in range(1, 11) if i in wres and wres[i].get("answer") == ans[str(i)])
    n_given = sum(1 for i in range(1, 11) if i in wres and wres[i].get("answer"))
    wrong = n_given - n_ok
    flags = {i: wres[i].get("flag") if i in wres else "none" for i in range(1, 11)}
    print(f'  识别 "{got}" / 真值 "{want}" → 答 {n_ok}/10，给出答案 {n_given} 题，其中自信错 {wrong}')
    print(f"  每题 flag: {flags}")
    print(f"  保守进复核 {10 - n_given} 题（multi/空框/低置信）")
    print("  （说明：putText 合成字体对几何特征不稳是已知边界，重点看链路机械正确 + 无自信错）")
    if wrong != 0:
        print("  ❌ 出现自信错 —— 违反铁律")
        return 1
    print("  🎉 无自信错：writebox 链路在部署的容器内工作正常（给出答案全对）")
    return 0

if __name__ == "__main__":
    if not os.path.isdir(FIX):
        print(f"缺少素材目录 {FIX}（需上传 template.json / 第01份_张一鸣_01.png / expected.json）")
        sys.exit(2)
    raise SystemExit(test_e2e_handwrite())