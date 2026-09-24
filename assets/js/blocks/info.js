// 模块：考生信息栏（班级/姓名/考号等手写栏 + 可选考号填涂区）
import { esc, commonStyle } from '../core/util.js';

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
        <input type="number" min="4" max="12" data-k="examDigits" value="${config.examDigits}">
      </label>
      <p class="hint">提示：启用填涂区后，班级/姓名/考号等手写栏会放在填涂区右侧，节省空间。</p>
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
    const gridHtml = this._gridHtml(config);
    const fieldRows = config.fields.map(f =>
      `<div class="info-field-row"><span class="lab">${esc(f.label)}</span><span class="il" style="width:${f.w}px"></span></div>`
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

  _gridHtml(config){
    if (!config.examGrid) return '';
    const n = Math.max(4, Math.min(12, +config.examDigits || 8));
    let head = '<tr><th></th>' + Array.from({ length: n }, (_, i) => `<th class="pos">${i + 1}</th>`).join('') + '</tr>';
    let rows = '';
    for (let d = 0; d <= 9; d++){
      rows += `<tr><td class="pos">${d}</td>` + Array.from({ length: n }, () => `<td><span class="ebrk"></span></td>`).join('') + '</tr>';
    }
    return `<div class="exam-grid"><div class="eg-title">考号填涂区（用 2B 铅笔填涂对应数字）</div>
      <table>${head}${rows}</table></div>`;
  }
};
