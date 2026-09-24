// 模块：考生信息栏（班级/姓名/考号等手写栏 + 可选考号填涂区）
import { esc, commonStyle, mmPx, probeSize } from '../core/util.js';
import { blockInnerMM, pageGeom } from '../core/geometry.js';

// 考号填涂区的宽度策略：
//   ① **宽度上限**：填涂区最多占「页面宽度」的 gridMaxPct%（默认 25%，即 1/4 页宽）——
//      「占比」是纸面上的直觉，所以基数取整页宽度（pw），不是栏宽；A3 横版同样成立。
//   ② 在上限内把格子撑到尽可能大（3–5mm），而不是跟着字号被动缩小；
//      相邻间距按格宽自适应（宽格留大间距、紧格贴紧排）。
//   ③ 若上限内连「可填涂下限 3mm」都放不下（位数多 / 纸小），才**放宽上限**——
//      但永不越过栏宽；这一步之前会先逐档压缩右侧手写栏。
const FIELDS_GAP_MM = 3.2;          // 填涂区与手写栏之间的间距，需与 CSS 的 .info-body gap 一致
const BRK_MIN_MM = 3.0;             // 填涂格边长下限（再小就不便于填涂）
const BRK_MAX_MM = 5.0;             // 填涂格边长上限（够大即可，避免格子巨大而显得空旷）
const FIELDS_MIN_SCALE = 0.6;       // 手写栏下划线最多压到原设定的 60%
const BASE_FONT_PX = 14;            // .blk 的基准字号，用于把「通用样式→字号」折算成尺寸缩放
const GRID_MAX_PCT = 25;            // 填涂区宽度上限默认值：页面宽度的 25%
const GRID_PCT_MIN = 10, GRID_PCT_MAX = 60;

// 相邻填涂格之间的空隙按格宽自适应：格宽时留大间距（清晰），格紧时贴紧排（把尺寸让给方框本身）——
// 真实机读卡也是这么做的，这样才能在位数很多时仍然保住「可填涂」的方框尺寸。
function cellGapMM(cellMM){
  if (cellMM >= 6) return 1.4;
  if (cellMM >= 5) return 1.0;
  return 0.7;
}

export default {
  type: 'info',
  name: '考生信息栏',
  icon: '🪪',
  defaults: () => ({
    title: '考 生 信 息',
    fields: [
      { label: '班级', w: 90 },
      { label: '姓名', w: 90 },
      { label: '考号', w: 120 }
    ],
    examGrid: false,
    examDigits: 8,
    gridMaxPct: GRID_MAX_PCT
  }),

  configUI(container, config, onChange){
    container.innerHTML = `
      <label>标题
        <input type="text" data-k="title" value="${esc(config.title)}">
      </label>
      <div class="qlist" id="field-list"></div>
      <button class="addbtn" data-act="add-field">+ 增加手写栏</button>
      <label style="margin-top:12px;display:flex;align-items:center;gap:6px;">
        <input type="checkbox" data-k="examGrid" ${config.examGrid ? 'checked' : ''}> 启用考号填涂区
      </label>
      <div class="row">
        <label>考号位数
          <input type="number" min="4" max="20" data-k="examDigits" value="${config.examDigits}">
        </label>
        <label>最大占比(% 页宽)
          <input type="number" min="10" max="60" step="5" data-k="gridMaxPct" value="${config.gridMaxPct ?? GRID_MAX_PCT}">
        </label>
      </div>
      <p class="hint">填涂区宽度默认不超过<b>页面宽度的 1/4</b>（可调 10–60%），剩余宽度由右侧手写栏下划线拉满。上限内会把方框撑到尽量大（3–5mm），保证可填涂、可读；只有上限内连 3mm 都放不下时（位数很多或纸张较小）才自动放宽，且永不超出纸张。</p>
      <p class="hint"><b>启用考号填涂区</b>后，扫描识别服务能把考号直接从卷面上读出来 —— 一个班的扫描件可以随便命名、打包成一个 zip 丢进去即可。不启用的话，就只能靠<b>文件名或目录名里带考号</b>来分组（也可以用，但得先给文件改名）。</p>
    `;
    const list = container.querySelector('#field-list');
    const renderList = () => {
      list.innerHTML = config.fields.map((f, i) => `
        <div class="qrow">
          <span>栏 ${i + 1}</span>
          <input type="text" data-i="${i}" data-f="label" value="${esc(f.label)}" placeholder="标签">
          <input type="number" data-i="${i}" data-f="w" value="${f.w}" title="下划线宽度(px)">
          <button data-del="${i}" class="danger">✕</button>
        </div>`).join('');
      list.querySelectorAll('[data-f]').forEach(inp => inp.addEventListener('input', e => {
        const i = +e.target.dataset.i;
        const f = e.target.dataset.f;
        config.fields[i][f] = (f === 'w') ? (parseInt(e.target.value) || 60) : e.target.value;
        onChange();
      }));
      list.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', e => {
        config.fields.splice(+e.target.dataset.del, 1);
        if (config.fields.length === 0) config.fields.push({ label: '栏', w: 90 });
        renderList(); onChange();
      }));
    };
    renderList();
    container.querySelector('[data-act="add-field"]').addEventListener('click', () => {
      config.fields.push({ label: '栏', w: 90 }); renderList(); onChange();
    });
    container.querySelector('[data-k="title"]').addEventListener('input', e => { config.title = e.target.value; onChange(); });
    container.querySelector('[data-k="examGrid"]').addEventListener('change', e => { config.examGrid = e.target.checked; onChange(); });
    container.querySelector('[data-k="examDigits"]').addEventListener('input', e => { config.examDigits = parseInt(e.target.value) || 8; onChange(); });
    container.querySelector('[data-k="gridMaxPct"]').addEventListener('input', e => {
      const v = parseInt(e.target.value);
      config.gridMaxPct = isNaN(v) ? GRID_MAX_PCT : Math.max(GRID_PCT_MIN, Math.min(GRID_PCT_MAX, v));
      onChange();
    });
  },

  render(config){
    const style = commonStyle(config);
    // 统一算一次布局：填涂格边长 + 手写栏压缩比 + 填涂区宽度，供两侧共用
    const lay = config.examGrid ? this._layout(config) : { brk: 0, fieldScale: 1, gridMM: 0 };
    const gridHtml = config.examGrid ? this._gridHtml(config, lay) : '';

    const w = px => Math.max(12, Math.round(px * lay.fieldScale));
    const fieldRows = config.fields.map(f =>
      `<div class="info-field-row"><span class="lab">${esc(f.label)}</span><span class="il" style="min-width:${w(f.w)}px"></span></div>`
    ).join('');

    if (config.examGrid && gridHtml){
      return `<div class="blk" style="${style}"><div class="info-box">
        <div class="ib-title">${esc(config.title)}</div>
        <div class="info-body">
          ${gridHtml}
          <div class="info-fields-col">${fieldRows}</div>
        </div>
      </div></div>`;
    }
    return `<div class="blk" style="${style}"><div class="info-box">
      <div class="ib-title">${esc(config.title)}</div>
      <div class="info-fields">${config.fields.map(f =>
        `<span class="info-field"><span class="lab">${esc(f.label)}</span><span class="il" style="width:${f.w}px"></span></span>`
      ).join('')}</div>
    </div></div>`;
  },

  /* ---------- 考号填涂区 ---------- */

  _digits(config){
    return Math.max(4, Math.min(20, +config.examDigits || 8));
  },

  _tableInner(n){
    // 顶部：考号标题（跨列）
    const head = `<tr><th class="eg-head" colspan="${n}">考 号</th></tr>`;
    // 手写行：空框，供考生手写考号
    const write = `<tr>${Array.from({ length: n }, () => '<td class="write"></td>').join('')}</tr>`;
    // 数字行：中括号内即为数字（0–9），一排数字即可
    // data-pos（第几位，1 起算）/ data-digit 供「导出阅卷模板」定位每个填涂格 ——
    // 扫描端靠这两个钩子把考号从卷面上读出来，老师就不用把考号写进文件名了。
    // 离屏实测（_tableMM）也走这个函数，所以量到的尺寸与真实渲染完全一致。
    let rows = '';
    for (let d = 0; d <= 9; d++){
      rows += `<tr>${Array.from({ length: n }, (_, i) =>
        `<td><span class="ebrk" data-pos="${i + 1}" data-digit="${d}">${d}</span></td>`).join('')}</tr>`;
    }
    return head + write + rows;
  },

  // 离屏实测：该字号下「整张填涂表」的自然宽度(mm)（宽度改回 auto，避免 width:100% 造成循环）
  _tableMM(n, fs){
    const { width } = probeSize(
      `<div class="exam-grid"><table style="font-size:${fs}em;width:auto;table-layout:auto">${this._tableInner(n)}</table></div>`,
      'table'
    );
    return width / mmPx();
  },

  // 右侧手写栏的自然宽度(mm)：标签字数 × 1em + 间距 + 下划线宽度（可整体按 scale 压缩）
  _fieldsMM(config, scale){
    const px = mmPx();
    const widest = config.fields.reduce((m, f) =>
      Math.max(m, String(f.label || '').length * BASE_FONT_PX + 6 + (+f.w || 60) * scale), 0);
    return widest / px;
  },

  // 布局：先按「页面 1/4 宽度」上限反推填涂格边长，放不下下限时再逐级放宽
  _layout(config){
    const n = this._digits(config);
    const innerMM = blockInnerMM();
    const px = mmPx();
    const pct = Math.max(GRID_PCT_MIN, Math.min(GRID_PCT_MAX, +(config.gridMaxPct ?? GRID_MAX_PCT) || GRID_MAX_PCT));
    // 「占比」的基数取整页宽度（纸面直觉），不是栏宽
    const capMM = pageGeom().pw * pct / 100;
    // 填涂区自身占用的宽度：左右 padding(0.5em) + 边框(1.5px)
    const gridChromeMM = (2 * 0.5 * BASE_FONT_PX + 2 * 1.5) / px;
    // 「通用样式 → 字号」按比例放大填涂格（默认 14px 时不缩放）
    const fontScale = (parseFloat(config.style && config.style.fontSize) || BASE_FONT_PX) / BASE_FONT_PX;
    const brkMax = BRK_MAX_MM * fontScale;
    const brkMin = BRK_MIN_MM * fontScale;

    // 给定可用宽度 → 该宽度下能放下的格子边长（受上限约束）
    const brkIn = avail => {
      const cell = (avail - gridChromeMM) / n;
      const gap = cellGapMM(cell);
      return { cell, gap, brk: Math.min(brkMax, cell - gap) };
    };
    // 理想宽度：在「上限」内把格子撑到上限尺寸
    const idealMM = Math.min(capMM, n * (brkMax + cellGapMM(brkMax)) + gridChromeMM);

    // 手写栏压缩比：只有「填涂区（按上限取宽）+ 手写栏」超出一栏时才逐档压缩
    let fieldScale = 1;
    while (fieldScale > FIELDS_MIN_SCALE &&
           idealMM + FIELDS_GAP_MM + this._fieldsMM(config, fieldScale) > innerMM + 0.01){
      fieldScale = +(fieldScale - 0.1).toFixed(2);
    }

    // 栏宽给填涂区的绝对上限（硬约束：绝不溢出）
    const hardMax = Math.max(0, innerMM - FIELDS_GAP_MM - this._fieldsMM(config, fieldScale));

    // ① 先在上限内排：avail = min(页面占比上限, 栏宽上限)
    let avail = Math.min(capMM, hardMax);
    let f = brkIn(avail);
    // ② 上限内连「可填涂下限」都放不下 → 放宽上限到「刚好放得下下限」（仍不越过栏宽）
    if (f.brk < brkMin){
      const needMM = n * (brkMin + cellGapMM(brkMin + 0.7)) + gridChromeMM;
      avail = Math.min(hardMax, Math.max(avail, needMM));
      f = brkIn(avail);
    }

    const brk = Math.max(0.8, Math.min(brkMax, f.brk));
    const gridMM = Math.max(12, n * (brk + f.gap) + gridChromeMM);
    return {
      brk, gap: f.gap, fieldScale, gridMM,
      // 供校验 / 调试：上限是否被突破（只可能是「保住可填涂」这一步）
      capMM, pct, exceededCap: gridMM > capMM + 0.05
    };
  },

  _gridHtml(config, lay){
    const n = this._digits(config);
    // data-sid 标记「这一块是考号填涂区」，导出阅卷模板时据此收集
    return `<div class="exam-grid" data-sid="1" style="width:${lay.gridMM.toFixed(2)}mm;--brk:${lay.brk.toFixed(2)}mm">`
      + `<table>${this._tableInner(n)}</table></div>`;
  }
};
