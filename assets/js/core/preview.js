// 预览渲染：固定纸张分页（item 2）
// 纸张大小固定，不随内容变化；内容先填满 A3 第一面（双栏），再第二面，再第二页第一面……
// 实现：JS 分页引擎 —— 测量每个区块真实高度，按固定页高塞入固定尺寸 .page 卡片。
import { store } from './store.js';
import { registry } from './registry.js';
import { mmPx } from './util.js';
import { pageGeom, MARK_INSET, COL_GAP_MM } from './geometry.js';

export function renderPreview(el){
  // 几何（含定位点占用的页边距带）统一由 geometry.js 提供，不再本地硬编码
  const g = pageGeom();
  const { pw, ph, padX, padY, cols, colW, markStyle, markSize, contentH } = g;
  const mm = mmPx();
  const contentHpx = contentH * mm;
  const marginPx = 6 * mm;                 // .blk margin-bottom

  // 1) 渲染所有区块为真实 DOM，便于测量高度
  const meas = document.createElement('div');
  meas.style.cssText = 'position:absolute;left:-99999px;top:0;visibility:hidden;';
  meas.style.width = pw + 'mm';
  document.body.appendChild(meas);

  const blockEls = store.blocks.map(b => {
    const mod = registry.get(b.type);
    const wrap = document.createElement('div');
    if (mod){
      try { wrap.innerHTML = mod.render(b.config); }
      catch(e){ wrap.innerHTML = `<div class="blk" style="color:#c0392b">[渲染错误:${b.type}]</div>`; }
    }
    meas.appendChild(wrap);
    return wrap.firstElementChild; // 真实 .blk 元素
  });

  // 2) 分页：每面一张固定尺寸卡片；A3 面内按 2 栏排布
  const pages = [];
  let colHeights = new Array(cols).fill(0);
  let cur = null;

  function newPage(){
    cur = document.createElement('div');
    cur.className = 'page';
    cur.style.cssText = `width:${pw}mm;height:${ph}mm;padding:${padY}mm ${padX}mm;`;
    cur._cols = [];
    for (let c = 0; c < cols; c++){
      const col = document.createElement('div');
      col.className = 'col';
      if (cols > 1) col.style.marginRight = (c < cols - 1 ? COL_GAP_MM + 'mm' : '0');
      cur.appendChild(col);
      cur._cols.push(col);
    }
    pages.push(cur);
    colHeights = new Array(cols).fill(0);
    return cur;
  }
  if (store.blocks.length) newPage();

  for (const blk of blockEls){
    // 在栏宽下测量该区块高度（px）
    const probe = document.createElement('div');
    probe.style.cssText = `position:absolute;left:-99999px;top:0;width:${colW}mm;visibility:hidden;`;
    probe.appendChild(blk);
    meas.appendChild(probe);
    const bh = blk.getBoundingClientRect().height;
    probe.remove();

    // 选当前最矮的栏
    let target = 0;
    for (let c = 1; c < cols; c++) if (colHeights[c] < colHeights[target]) target = c;

    // 当前面放不下且本面已有内容 -> 新面
    if (colHeights[target] + bh + marginPx > contentHpx && colHeights[target] > 0.5){
      newPage();
      target = 0;
    }
    cur._cols[target].appendChild(blk);
    colHeights[target] += bh + marginPx;
  }

  meas.remove();

  // 2.5) 定位点：每一面（.page 卡片）只要有题目内容，就在四角补定位点；
  //      空白面不加。绝对定位在「页边距带」内，不参与排版流、不覆盖内容。
  if (markStyle !== 'none'){
    const CORNER = {
      tl: ['top', 'left'], tr: ['top', 'right'],
      bl: ['bottom', 'left'], br: ['bottom', 'right']
    };
    for (const p of pages){
      if (!p._cols.some(c => c.children.length > 0)) continue; // 空面跳过
      for (const pos of ['tl', 'tr', 'bl', 'br']){
        const m = document.createElement('div');
        m.className = 'cmark' + (markStyle === 'triangle' ? ' tri' : '') + ' ' + pos;
        m.style.width = markSize + 'mm';
        m.style.height = markSize + 'mm';
        m.style[CORNER[pos][0]] = MARK_INSET + 'mm';
        m.style[CORNER[pos][1]] = MARK_INSET + 'mm';
        p.appendChild(m);
      }
    }
  }

  // 3) 输出
  el.innerHTML = '';
  pages.forEach(p => el.appendChild(p));
}
