// 模块：选择题（填涂 / 手写 两种作答样式；任意选项数量，字母 A..Z, AA, AB, ...）
import { esc, commonStyle, mmPx, probeSize } from '../core/util.js';
import { blockInnerMM } from '../core/geometry.js';

const MAX_OPTIONS = 60;

// 旧模板迁移：早期版本把「作答样式」存在 config.style（字符串 'bubble'/'handwrite'），
// 与「通用样式」对象（config.style.fontSize / .align）同名冲突 ——
// ES Module 严格模式下 `'bubble'.fontSize = 18` 会抛 TypeError，
// 导致选择题的「字号 / 对齐」控件完全失效、且作答样式被静默改写。
// 现统一：作答样式 → config.mode；通用样式 → config.style（对象）。
function normalize(config){
  if (!config) return config;
  if (typeof config.style === 'string'){
    config.mode = config.style;
    config.style = {};
  }
  if (!config.mode) config.mode = 'bubble';
  if (!config.style || typeof config.style !== 'object') config.style = {};
  return config;
}

// 0 -> A, 25 -> Z, 26 -> AA, 27 -> AB, ...（类似表格列名）
function colLabel(i){
  let s = '', n = i;
  do { s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return s;
}
function optLabels(n){
  return Array.from({ length: n }, (_, i) => colLabel(i));
}

// 单题 HTML：题号与选项分离 —— .scn 固定不换行，.opts 内每个选项是原子块（不会跨行拆开），
// 放不下时整块下移，避免「题号孤零零占一行」或「选项被劈成两半」。
function qHtml(no, letters, mode){
  if (mode !== 'bubble') return `<div class="scq hw"><span class="scn">${no}.</span><span class="hw-line"></span></div>`;
  const cells = letters.map(l => `<span class="bub"><span class="bracket">${l}</span></span>`).join('');
  return `<div class="scq"><span class="scn">${no}.</span><span class="opts">${cells}</span></div>`;
}

export default {
  type: 'singleChoice',
  name: '选择题',
  icon: '☑',
  defaults: () => ({ title: '一、选择题', count: 10, cols: 5, options: 4, mode: 'bubble', hwGap: 1, startNo: 1 }),

  configUI(container, config, onChange){
    normalize(config);
    container.innerHTML = `
      <label>标题
        <input type="text" data-k="title" value="${esc(config.title)}">
      </label>
      <div class="row">
        <label>题数
          <input type="number" min="1" max="80" data-k="count" value="${config.count}">
        </label>
        <label>每行题数
          <input type="number" min="1" max="10" data-k="cols" value="${config.cols}">
        </label>
      </div>
      <div class="row">
        <label>选项数
          <input type="number" min="2" max="60" data-k="options" value="${config.options}">
        </label>
        <label>起始题号
          <input type="number" min="1" max="200" data-k="startNo" value="${config.startNo}">
        </label>
      </div>
      <div class="row">
        <label>作答样式
          <select data-k="mode">
            <option value="bubble">填涂（中括号）</option>
            <option value="handwrite">手写（横线）</option>
          </select>
        </label>
        <label>行间距(mm)
          <input type="number" min="0.5" max="30" step="0.5" data-k="hwGap" value="${config.hwGap ?? 1}">
        </label>
      </div>
      <p class="hint">「行间距」控制每题之间的垂直距离（手写样式下尤其需要留出书写空间）。「每行题数」为上限：空间不足时会自动减少列数，保证每道题的题号与全部选项都排在同一行内。选项超过 26 个用 AA、AB… 续排；选项多到一行放不下时该题独占一栏，按行排满后换行，不会超出纸张。</p>
    `;
    container.querySelector('[data-k="mode"]').value = config.mode;
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
    normalize(config);
    const opts = Math.max(2, Math.min(MAX_OPTIONS, +config.options || 4));
    const letters = optLabels(opts);
    const start = Math.max(1, +config.startNo || 1);
    const count = Math.max(1, +config.count || 1);
    const style = commonStyle(config);
    // 行间距：手写（横线）样式尤其需要留出书写空间；由 .sc-grid 的 row-gap 读取
    const hwGap = Math.max(0.5, Math.min(30, parseFloat(config.hwGap) || 1));

    const cols = this._fitCols(config, letters, style);

    let rows = '';
    for (let i = 0; i < count; i++) rows += qHtml(start + i, letters, config.mode);

    return `<div class="blk" style="${style};--hg:${hwGap}mm"><div class="blk-title">${esc(config.title)}</div>
      <div class="sc-grid" style="grid-template-columns:repeat(${cols},minmax(0,1fr))">${rows}</div></div>`;
  },

  // 计算列数：保证「题号 + 全部选项」在单行内完整排下。
  // 排不下的整题换到下一行，而不是把某题的最后一个选项挤到第二行。
  // 关键在于「实测」而不是估算：把单题渲染到离屏容器里量真实宽度，
  // 这样字号、字体度量、多字符字母（AA…）都能自动算准。
  _fitCols(config, letters, style){
    const px = mmPx();
    const innerPx = blockInnerMM() * px;  // 单栏真正可用的内容宽度（已扣 .blk 的 padding 与边框）
    const gapPx = 12;                     // .sc-grid 列间距

    // 实测单题（题号 + 全部选项）所需宽度
    const probe = probeSize(
      `<div class="blk" style="${style}"><div class="sc-grid" style="grid-template-columns:max-content">${qHtml(1, letters, config.mode)}</div></div>`,
      '.scq'
    );
    const qPx = probe.width;
    // 留 1% 余量：不同机器 / 浏览器的字体度量有亚像素差异，避免卡在临界值而掉列
    const qSafe = qPx * 1.01;

    // 测量失败（无 DOM 环境）→ 退回保守估算
    if (!qPx) return Math.min(Math.max(1, +config.cols || 1), 3);

    // 单题一行都放不下（选项极多）→ 单栏，选项在 .opts 内排满一行后换行
    if (qSafe > innerPx - 0.5) return 1;

    const maxCols = Math.max(1, Math.floor((innerPx + gapPx) / (qSafe + gapPx)));
    return Math.min(maxCols, Math.max(1, +config.cols || 1));
  }
};
