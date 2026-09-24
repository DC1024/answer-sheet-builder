// 模块：解答题（空白大框，可设高度；无横线、无“本题满分”）
import { esc, commonStyle } from '../core/util.js';

export default {
  type: 'answer',
  name: '解答题',
  icon: '📐',
  defaults: () => ({ title: '三、解答题', startNo: 13, lined: false, lineGap: 8, questions: [ { h: 160 } ] }),

  configUI(container, config, onChange){
    container.innerHTML = `
      <label>标题
        <input type="text" data-k="title" value="${esc(config.title)}">
      </label>
      <label>起始题号
        <input type="number" min="1" max="200" data-k="startNo" value="${config.startNo}">
      </label>
      <label>作答区样式
        <select data-k="lined">
          <option value="false">空白</option>
          <option value="true">横线</option>
        </select>
      </label>
      <label>横线间距（mm，仅横线样式生效）
        <input type="number" min="4" max="20" data-k="lineGap" value="${config.lineGap ?? 8}">
      </label>
      <p class="hint">每题高度单位 mm，越大作答空间越大。建议各题高度保持一致。横线样式会在作答区内画出等距横线。</p>
      <div class="qlist" id="ans-list"></div>
      <button class="addbtn" data-act="add">+ 增加一题</button>
    `;
    const list = container.querySelector('#ans-list');
    const renderList = () => {
      list.innerHTML = config.questions.map((q, i) => `
        <div class="qrow">
          <span>第 ${i + 1} 题</span>
          <label style="margin:0;">高度(mm)
            <input type="number" min="40" max="400" data-i="${i}" data-f="h" value="${q.h}">
          </label>
          <button data-del="${i}" class="danger">✕</button>
        </div>`).join('');
      list.querySelectorAll('[data-f="h"]').forEach(inp => inp.addEventListener('input', e => {
        config.questions[+e.target.dataset.i].h = parseInt(e.target.value) || 80; onChange();
      }));
      list.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', e => {
        config.questions.splice(+e.target.dataset.del, 1);
        if (config.questions.length === 0) config.questions.push({ h: 160 });
        renderList(); onChange();
      }));
    };
    renderList();
    container.querySelector('[data-act="add"]').addEventListener('click', () => { config.questions.push({ h: 160 }); renderList(); onChange(); });
    container.querySelector('[data-k="title"]').addEventListener('input', e => { config.title = e.target.value; onChange(); });
    container.querySelector('[data-k="startNo"]').addEventListener('input', e => { config.startNo = parseInt(e.target.value) || 1; onChange(); });
    const linedSel = container.querySelector('[data-k="lined"]');
    linedSel.value = String(!!config.lined);
    linedSel.addEventListener('change', e => { config.lined = (e.target.value === 'true'); onChange(); });
    container.querySelector('[data-k="lineGap"]').addEventListener('input', e => { config.lineGap = parseInt(e.target.value) || 8; onChange(); });
  },

  render(config){
    const start = Math.max(1, +config.startNo || 1);
    const lined = !!config.lined;
    const lg = Math.max(4, parseInt(config.lineGap) || 8);
    const qs = config.questions.map((q, i) => {
      const h = Math.max(40, +q.h || 120);
      const abCls = lined ? 'ab lined' : 'ab';
      const abStyle = lined ? `--lg:${lg}mm` : '';
      return `<div class="ans-box" style="height:${h}mm">
        <div class="ah">${start + i}.</div><div class="${abCls}" style="${abStyle}"></div></div>`;
    }).join('');
    return `<div class="blk" style="${commonStyle(config)}"><div class="blk-title">${esc(config.title)}</div>${qs}</div>`;
  }
};
