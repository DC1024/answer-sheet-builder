// 模块：考生信息栏（班级/姓名/考号等手写栏 + 可选考号填涂区）
import { esc, commonStyle, mmPx, probeSize } from '../core/util.js';
import { blockInnerMM } from '../core/geometry.js';

// 考号填涂区的宽度策略：
//   左侧填涂格要「可填涂、可读」，右侧手写栏可以「适量压榨」。
//   ① 填涂格尺寸直接由「可用宽度 ÷ 位数」反推（3–5mm），而不是跟着字号被动缩小 ——
//      这样位数再多也先把格子撑到能填的大小；
//   ② 只有气泡会小于 3mm 时才逐档压缩右侧手写栏下划线（下限 60%）；
//   ③ 填涂区只占「气泡真正需要的宽度」，剩余宽度留给右侧手写栏把下划线拉满，避免右侧留白。
const FIELDS_GAP_MM = 3.2;          // 填涂区与手写栏之间的间距，需与 CSS 的 .info-body gap 一致
const BRK_MIN_MM = 3.0;             // 填涂格边长下限（再小就不便于填涂）
const BRK_MAX_MM = 5.0;             // 填涂格边长上限（够大即可，避免格子巨大而显得空旷）
const FIELDS_MIN_SCALE = 0.6;       // 手写栏下划线最多压到原设定的 60%
const BASE_FONT_PX = 14;            // .blk 的基准字号，用于把「通用样式→字号」折算成尺寸缩放

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
    examDigits: 8
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
      <label>考号位数
        <input type="number" min="4" max="20" data-k="examDigits" value="${config.examDigits}">
      </label>
      <p class="hint">启用后手写栏移到填涂区右侧：填涂区宽度按「格子可填涂所需的大小」自动确定，剩余宽度由手写栏下划线拉满（所填宽度作为最小值）。位数较多时会先从手写栏让出空间，仍不够才缩小格子，绝不超出纸张。</p>
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
    let rows = '';
    for (let d = 0; d <= 9; d++){
      rows += `<tr>${Array.from({ length: n }, () => `<td><span class="ebrk">${d}</span></td>`).join('')}</tr>`;
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

  // 布局：由可用宽度反推填涂格边长；必要时压缩右侧手写栏
  _layout(config){
    const n = this._digits(config);
    const innerMM = blockInnerMM();
    const px = mmPx();
    // 填涂区自身占用的宽度：左右 padding(0.5em) + 边框(1.5px)
    const gridChromeMM = (2 * 0.5 * BASE_FONT_PX + 2 * 1.5) / px;
    // 「通用样式 → 字号」按比例放大填涂格（默认 14px 时不缩放）
    const fontScale = (parseFloat(config.style && config.style.fontSize) || BASE_FONT_PX) / BASE_FONT_PX;
    const brkMax = BRK_MAX_MM * fontScale;
    const brkMin = BRK_MIN_MM * fontScale;

    // 给定手写栏压缩比时，能分给每个格子的边长与自适应间距
    const fitOf = scale => {
      const avail = innerMM - this._fieldsMM(config, scale) - FIELDS_GAP_MM;
      const cell = (avail - gridChromeMM) / n;
      const gap = cellGapMM(cell);
      return { avail, cell, gap, brk: Math.min(brkMax, cell - gap) };
    };

    // 优先保持手写栏设定宽度；只有填涂格会小于下限时才逐档压榨
    let fieldScale = 1;
    while (fieldScale > FIELDS_MIN_SCALE && fitOf(fieldScale).brk < brkMin){
      fieldScale = +(fieldScale - 0.1).toFixed(2);
    }
    if (fieldScale < FIELDS_MIN_SCALE) fieldScale = FIELDS_MIN_SCALE;

    const fit = fitOf(fieldScale);
    const brk = Math.max(brkMin, Math.min(brkMax, fit.brk));
    // 填涂区只占「气泡所需宽度」，余量留给右侧手写栏拉满下划线
    const gridMM = Math.max(30, Math.min(fit.avail, n * (brk + fit.gap) + gridChromeMM));
    return { brk, gap: fit.gap, fieldScale, gridMM };
  },

  _gridHtml(config, lay){
    const n = this._digits(config);
    return `<div class="exam-grid" style="width:${lay.gridMM.toFixed(2)}mm;--brk:${lay.brk.toFixed(2)}mm">`
      + `<table>${this._tableInner(n)}</table></div>`;
  }
};
