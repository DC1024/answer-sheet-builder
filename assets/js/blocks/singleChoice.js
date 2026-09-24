// 模块：选择题（支持 填涂 / 手写 两种作答样式）
import { esc, commonStyle } from '../core/util.js';
import { store } from '../core/store.js';

const LETTERS = ['A','B','C','D','E','F'];

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
        <label>选项数
          <select data-k="options">
            <option value="3">3 (A-C)</option>
            <option value="4">4 (A-D)</option>
            <option value="5">5 (A-E)</option>
          </select>
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
    `;
    container.querySelector('[data-k="options"]').value = String(config.options);
    container.querySelector('[data-k="style"]').value = config.style;
    container.querySelectorAll('[data-k]').forEach(el => {
      const ev = (el.tagName === 'SELECT') ? 'change' : 'input';
      el.addEventListener(ev, () => {
        let v = el.value;
        if (el.type === 'number') v = parseInt(v) || 0;
        config[el.dataset.k] = v;
        onChange();
      });
    });
  },

  render(config){
    const opts = Math.max(2, Math.min(6, +config.options || 4));
    const letters = LETTERS.slice(0, opts);
    const start = Math.max(1, +config.startNo || 1);
    const count = Math.max(1, +config.count || 1);
    const style = commonStyle(config);

    // 根据纸张计算可用列宽，防止溢出
    const cols = this._fitCols(config, opts);

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

  // 计算不溢出的列数：A3 双栏时按 A4 栏宽算；A4 按整张宽度算
  _fitCols(config, opts){
    const { size, orientation } = store.paper;
    const sheetW = (size === 'A3') ? 297 : 210;
    // 减去两侧 padding 7mm +（双栏时减去 column-gap 6mm）
    const usable = size === 'A3'
      ? (sheetW - 14 - 6) / 2
      : (sheetW - 14);
    // 每题最小宽度（mm）：题号约 6mm + 选项框 7mm/个 + 间隙
    const minW = config.style === 'bubble'
      ? (6 + opts * 7 + (opts - 1) * 1.5)
      : 42;
    const gap = 4; // 列间距约 4mm
    const maxCols = Math.max(1, Math.floor((usable + gap) / (minW + gap)));
    return Math.min(maxCols, Math.max(1, +config.cols || 1));
  }
};
