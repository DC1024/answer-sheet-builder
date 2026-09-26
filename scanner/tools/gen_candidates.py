# -*- coding: utf-8 -*-
"""为 31–60（手写版）答题卡生成「OpenCV 候选标签 + 可视化校对板」。

真值缺失时无法直接监督训练，本脚本先把每张手写字形用现成 OpenCV 分类器
读一遍，产出：
  - handwritten_raw/<sheet>_<q>.png   单字归一化图（白底黑字，便于人眼核对）
  - candidates_31_60.json             结构化候选（sheet/q/cand/conf/flag/feat）
  - candidates_31_60.csv              纯文本表（适合 grep / 表格软件）
  - review_31_60.html                 单文件交互校对板：点错字即可改，一键导标
                                       → 导出 labels_31_60.json（训练用真值）

裁剪方式 100% 复刻线上 decode_write（warp px=8.0，write 框全幅无 shrink），
所以 OpenCV 候选 = 生产链路同一输入下的判读，可信度高。

用法：python tools/gen_candidates.py
"""
import os
import sys
import csv
import json
import base64

import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import omr, hwletter  # noqa: E402

FIX = os.path.join(HERE, '..', 'tests', 'fixtures', 'real30')
RAW = os.path.join(FIX, 'handwritten_raw')
os.makedirs(RAW, exist_ok=True)

PX = 8.0  # 与 decode_write / extract_handwritten 完全一致


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def disp_tile(glyph):
    """48x48 归一化掩码（墨=255）→ 白底黑字显示图，便于人眼核对。"""
    if glyph is None:
        tile = np.full((48, 48), 255, np.uint8)
    else:
        tile = (255 - glyph).astype(np.uint8)  # 反色：白底黑字
    ok, buf = cv2.imencode('.png', tile)
    return base64.b64encode(buf).decode('ascii') if ok else ''


def main():
    tpl = omr.load_template(open(os.path.join(FIX, 'template_write.json'),
                                 encoding='utf-8').read())
    files = sorted(f for f in os.listdir(FIX)
                   if f.lower().endswith('.png') and f.startswith('第'))
    records = []
    stats = {'ok': 0, 'doubt': 0, 'faint': 0, 'multi': 0, 'blank': 0,
             'extract_fail': 0, 'files': 0}

    for fn in files:
        key = fn.split('_')[0].replace('第', '').replace('份', '')
        try:
            kn = int(key)
        except ValueError:
            continue
        if not (31 <= kn <= 60):          # 只处理手写版
            continue
        stats['files'] += 1
        name = fn.split('_')[1] if '_' in fn else ''
        bgr = imread_cn(os.path.join(FIX, fn))
        quad, _ = omr.detect_marks(bgr, tpl, 0)
        warp, px = omr.warp_page(bgr, quad, tpl, PX)
        _, thr = omr._prep(warp)
        page = tpl['pages'][0]
        for q in page['questions']:
            wb = q.get('write')
            if not wb:
                continue
            cx, cy = wb['x'] * px, wb['y'] * px
            rx = max(2.0, wb['w'] * px / 2.0)
            ry = max(2.0, wb['h'] * px / 2.0)
            x0, x1 = max(0, int(round(cx - rx))), int(round(cx + rx)) + 1
            y0, y1 = max(0, int(round(cy - ry))), int(round(cy + ry)) + 1
            box = thr[y0:y1, x0:x1]

            glyph, _ = hwletter.extract_glyph(box)
            res, meta = hwletter.classify_box(box)
            rid = f'{key}_{q["no"]:02d}'
            cand = res['letter'] if res else '?'
            conf = round(float(res['conf']), 2) if res else 0.0
            # 关键：confident 读（conf>=DOUBT_CONF）没有 flag_hint 键 → 必须补 'ok'，
            # 否则会被记成 None，误以为 OpenCV 全部失效。
            if res is None:
                flag = 'multi' if meta.get('multi') else 'blank'
            else:
                flag = res.get('flag_hint') or 'ok'
            if glyph is None:
                stats['extract_fail'] += 1
            if flag == 'ok':
                stats['ok'] += 1
            elif flag == 'doubt':
                stats['doubt'] += 1
            elif flag == 'faint':
                stats['faint'] += 1
            elif flag == 'multi':
                stats['multi'] += 1
            elif flag == 'blank':
                stats['blank'] += 1

            # 显示图落盘（相对路径供 HTML 引用）+ base64 备用
            tile = (255 - glyph).astype(np.uint8) if glyph is not None \
                else np.full((48, 48), 255, np.uint8)
            cv2.imencode('.png', tile)[1].tofile(os.path.join(RAW, f'{rid}.png'))

            feat = res.get('features', {}) if res else {}
            records.append({
                'id': rid, 'sheet': key, 'name': name, 'q': q['no'],
                'cand': cand, 'conf': conf, 'flag': flag,
                'nh': feat.get('nh'), 'aspect': feat.get('aspect'),
                'top_w': feat.get('top_w'), 'bot_w': feat.get('bot_w'),
                'mid_right': feat.get('mid_right'),
                'mid_over_ends': feat.get('mid_over_ends'),
                'file': f'handwritten_raw/{rid}.png',
                'b64': disp_tile(glyph),
            })

    # JSON（含 base64，便于其它工具消费）
    with open(os.path.join(FIX, 'candidates_31_60.json'), 'w', encoding='utf-8') as fh:
        json.dump(records, fh, ensure_ascii=False)
    # CSV（纯文本，便于 grep / 表格软件快速扫）
    with open(os.path.join(FIX, 'candidates_31_60.csv'), 'w', encoding='utf-8-sig',
              newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['sheet', 'name', 'q', 'cand', 'conf', 'flag',
                    'nh', 'aspect', 'top_w', 'bot_w', 'mid_right', 'mid_over_ends'])
        for r in records:
            w.writerow([r['sheet'], r['name'], r['q'], r['cand'], r['conf'], r['flag'],
                        r['nh'], r['aspect'], r['top_w'], r['bot_w'],
                        r['mid_right'], r['mid_over_ends']])

    build_html(records, os.path.join(FIX, 'review_31_60.html'))

    print(f'[完成] 处理手写卷 {stats["files"]} 份，提取字形 {len(records)} 个')
    print(f'[统计] ok={stats["ok"]} doubt={stats["doubt"]} faint={stats["faint"]} '
          f'multi={stats["multi"]} blank={stats["blank"]} extract_fail={stats["extract_fail"]}')
    print('[输出] candidates_31_60.json / .csv / review_31_60.html / handwritten_raw/')


def build_html(records, path):
    data = json.dumps(
        [{'id': r['id'], 'sheet': r['sheet'], 'name': r['name'], 'q': r['q'],
          'cand': r['cand'], 'conf': r['conf'], 'flag': r['flag'],
          'file': r['file'], 'b64': r['b64']} for r in records],
        ensure_ascii=False)
    html = HTML_TMPL.replace('__DATA__', data)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)


HTML_TMPL = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>31-60 手写字母 OpenCV 候选校对板</title>
<style>
  :root{--bg:#0b1020;--panel:#121a30;--panel2:#0e1626;--line:#22304d;
        --ink:#e7ecf5;--sub:#8aa0c8;--acc:#3da9fc;--ok:#39d98a;--warn:#ffb454;--bad:#ff6b6b;}
  *{box-sizing:border-box}
  body{margin:0;background:linear-gradient(180deg,#0b1020,#0a0f1c);color:var(--ink);
       font:14px/1.5 -apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:10;backdrop-filter:blur(8px);
         background:rgba(11,16,32,.86);border-bottom:1px solid var(--line);padding:12px 18px}
  h1{margin:0;font-size:16px;letter-spacing:.5px}
  .sub{color:var(--sub);font-size:12px;margin-top:2px}
  .bar{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}
  button{cursor:pointer;border:1px solid var(--line);background:var(--panel);color:var(--ink);
         padding:6px 12px;border-radius:8px;font-size:13px}
  button:hover{border-color:var(--acc)}
  .pill{font-size:12px;color:var(--sub);border:1px solid var(--line);border-radius:999px;padding:3px 10px}
  #grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));
        gap:12px;padding:18px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
        padding:10px;position:relative;transition:.15s}
  .card.needs{border-color:var(--warn);box-shadow:0 0 0 1px var(--warn) inset}
  .card .top{display:flex;justify-content:space-between;align-items:center;color:var(--sub);font-size:12px}
  .card img{width:96px;height:96px;display:block;margin:8px auto;
            image-rendering:auto;background:#fff;border-radius:6px}
  .guess{text-align:center;font-size:11px;color:var(--sub);margin-top:4px}
  .pick{display:flex;gap:6px;justify-content:center;margin-top:6px}
  .pick b{font-size:22px;width:40px;text-align:center;border:1px solid var(--line);
          border-radius:8px;cursor:pointer;background:var(--panel2);user-select:none}
  .pick b:hover{border-color:var(--acc);color:var(--acc)}
  .flag{position:absolute;top:8px;right:8px;font-size:10px;padding:2px 6px;border-radius:6px}
  .flag.ok{background:rgba(57,217,138,.16);color:var(--ok)}
  .flag.doubt,.flag.faint{background:rgba(255,180,84,.16);color:var(--warn)}
  .flag.multi,.flag.blank{background:rgba(255,107,107,.16);color:var(--bad)}
  .flag.unknown{background:rgba(138,160,200,.16);color:var(--sub)}
</style></head>
<body>
<header>
  <h1>31-60 手写字母 · OpenCV 候选校对板</h1>
  <div class="sub">点击下方大字母即可修正（A→B→C→D→? 循环）。<b>橙色边框</b>=与 OpenCV 候选不一致，需重点核对。改完后点「导出 labels.json」。</div>
  <div class="bar">
    <span class="pill" id="prog">已校对 0 / 0</span>
    <span class="pill" id="needs">待重点核对 0</span>
    <button id="adopt">一键采纳全部 OpenCV 候选</button>
    <button id="export">导出 labels_31_60.json</button>
  </div>
</header>
<main id="grid"></main>
<script>
const DATA = __DATA__;
const ORDER = ['A','B','C','D','?'];
const sel = {};                       // id -> 当前最终选择
DATA.forEach(r => { sel[r.id] = r.cand; });
const grid = document.getElementById('grid');

function card(r){
  const cur = sel[r.id];
  const needs = (cur !== r.cand) ? ' needs' : '';
  const flag = r.flag || 'unknown';
  const el = document.createElement('div');
  el.className = 'card' + needs;
  el.innerHTML =
    '<span class="flag '+flag+'">'+flag+'</span>'+
    '<div class="top"><span>第'+r.sheet+'份</span><span>Q'+r.q+'</span></div>'+
    '<img src="data:image/png;base64,'+r.b64+'" alt="'+r.id+'">'+
    '<div class="guess">OpenCV: '+r.cand+' · 置信 '+Math.round(r.conf*100)+'%</div>'+
    '<div class="pick"><b data-id="'+r.id+'">'+cur+'</b></div>';
  el.querySelector('b').onclick = () => {
    const i = (ORDER.indexOf(sel[r.id]) + 1) % ORDER.length;
    sel[r.id] = ORDER[i];
    el.querySelector('b').textContent = sel[r.id];
    refresh();
  };
  return el;
}
function refresh(){
  let done = 0, needs = 0;
  DATA.forEach(r => { if(sel[r.id] !== '?') done++; if(sel[r.id] !== r.cand) needs++; });
  document.getElementById('prog').textContent = '已校对 '+done+' / '+DATA.length;
  document.getElementById('needs').textContent = '待重点核对 '+needs;
}
DATA.forEach(r => grid.appendChild(card(r)));
refresh();

document.getElementById('adopt').onclick = () => {
  DATA.forEach(r => sel[r.id] = r.cand);
  document.querySelectorAll('.pick b').forEach(b => b.textContent = sel[b.dataset.id]);
  document.querySelectorAll('.card').forEach(c => c.classList.remove('needs'));
  refresh();
};
document.getElementById('export').onclick = () => {
  const out = {};
  DATA.forEach(r => { if(sel[r.id] !== '?') out[r.id] = sel[r.id]; });
  const blob = new Blob([JSON.stringify(out, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'labels_31_60.json';
  a.click();
};
</script>
</body></html>
"""


if __name__ == '__main__':
    main()
