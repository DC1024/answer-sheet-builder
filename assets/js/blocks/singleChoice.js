// 模块：选择题（填涂 / 手写 两种作答样式；任意选项数量，字母 A..Z, AA, AB, ...）
import { esc, commonStyle } from '../core/util.js';
import { store } from '../core/store.js';

const MAX_OPTIONS = 60;

// 0 -> A, 25 -> Z, 26 -> AA, 27 -> AB, ...（类似表格列名）
function colLabel(i){
  let s = '', n = i;
  do { s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return s;
}
function optLabels(n){
  return Array.from({ length: n }, (_, i) => colLabel(i));
}

export default {
  type: 'singleChoice',
  name: '选择题',
  icon: '☑',
  defaults: () => ({ title: '一、选择题', count: 10, cols: 5, options: 4, style: 'bubble', startNo: 1 }),

  configUI(container, config, onChange){
    container.innerHTML = `
      <label>标题
        <input type="text" data-k="title" value="${esc(config.title)}">
      </label>
      <div class="row">
        <label>题数
          <input type="number" min="1" max="80" data-k="count" value="${config.count}">
        </label>
        <label>每行题数（目标值，空间不足会自动折行）
          <input type="number" min="1" max="10" data-k="cols" value="${config.cols}">
        </label>
      </div>
      <div class="row">
        <label>选项数（2–60）
          <input type="number" min="2" max="60" data-k="options" value="${config.options}">
        </label>
        <label>起始题号
          <input type="number" min="1" max="200" data-k="startNo" value="${config.startNo}">
        </label>
      </div>
      <label>作答样式
        <select data-k="style">
          <option value="bubble">填涂（中括号）</option>
          <option value="handwrite">手写（横线）</option>
        </select>
      </label>
      <p class="hint">选项超过 26 个后用 AA、AB… 续排；选项过多时该题会自动换行，且不会超出纸张宽度。</p>
    `;
    container.querySelector('[data-k="style"]').value = config.style;
    container.querySelectorAll('[data-k]').forEach(el => {
      const ev = (el.tagName === 'SELECT') ? 'change' : 'input';
      el.addEventListener(ev, () => {
        let v = el.value;
        if (el.type === 'number'){
          v = parseInt(v) || 0;
          if (el.dataset.k === 'options') v = Math.max(2, Math.min(MAX_OPTIONS, v || 2));
        }
        config[el.dataset.k] = v;
        onChange();
      });
    });
  },

  render(config){
    const opts = Math.max(2, Math.min(MAX_OPTIONS, +config.options || 4));
    const letters = optLabels(opts);
    const start = Math.max(1, +config.startNo || 1);
    const count = Math.max(1, +config.count || 1);
    const style = commonStyle(config);

    // 根据纸张与字号计算可用列数，防止溢出
    const cols = this._fitCols(config, opts, letters[opts - 1].length);

    let rows = '';
    for (let i = 0; i < count; i++){
      const no = start + i;
      if (config.style === 'bubble'){
        const cells = letters.map(l => `<span class="bub"><span class="bracket">${l}</span></span>`).join('');
        rows += `<div class="scq"><span class="scn">${no}.</span>${cells}</div>`;
      } else {
        rows += `<div class="scq hw"><span class="scn">${no}.</span><span class="hw-line"></span></div>`;
      }
    }
    return `<div class="blk" style="${style}"><div class="blk-title">${esc(config.title)}</div>
      <div class="sc-grid" style="grid-template-columns:repeat(${cols},minmax(0,1fr))">${rows}</div></div>`;
  },

  // 计算不溢出的列数：A3 双栏按 A4 栏宽算；A4 按整张宽算。
  // 若单个题目的选项一行都放不下（可用宽 < 单题宽），返回 1 栏并交给 CSS 自动换行。
  _fitCols(config, opts, maxLen = 1){
    const { size } = store.paper;
    const sheetW = (size === 'A3') ? 297 : 210;
    const usable = size === 'A3' ? (sheetW - 14 - 6) / 2 : (sheetW - 14); // mm

    const fontPx = parseFloat(config.style && config.style.fontSize) || 14;
    const emMM = fontPx * 0.264583;                 // 1em ≈ ? mm
    const gapMM = (12 / fontPx) * emMM;             // 栏间距约 12px

    // 单个选项占用宽度(em)：方框(1.215) + 右边距(约0.36) + 多字符字母余量
    const optEm = 1.215 + 0.36 + (maxLen > 1 ? 0.35 * (maxLen - 1) : 0);
    const qMM = (1.9 + opts * optEm) * emMM;        // 题号 + 全部选项

    if (qMM >= usable - 0.5) return 1;              // 一行放不下 → 单栏 + 自动换行
    const maxCols = Math.max(1, Math.floor((usable + gapMM) / (qMM + gapMM)));
    return Math.min(maxCols, Math.max(1, +config.cols || 1));
  }
};
