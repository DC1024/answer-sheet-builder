// 模块：填空题（支持多级小题，每空可独立设置长度）
import { esc, commonStyle } from '../core/util.js';

const blankDef = () => ({ len: 30 });
const nodeDef = (isRoot) => ({ label: isRoot ? '' : '（1）', blanks: [blankDef()], subs: [] });

// 兼容旧模板：以前 questions 的 blanks 是数字
function normalize(config){
  if (!Array.isArray(config.questions)) config.questions = [];
  config.questions = config.questions.map(q => {
    if (typeof q.blanks === 'number'){
      const n = Math.max(1, parseInt(q.blanks) || 1);
      return { label: '', blanks: Array.from({ length: n }, blankDef), subs: [] };
    }
    return q;
  });
  if (config.questions.length === 0){
    config.questions = [
      { label: '', blanks: [], subs: [
        { label: '（1）', blanks: [blankDef(), blankDef()], subs: [] },
        { label: '（2）', blanks: [], subs: [
          { label: '①', blanks: [blankDef()], subs: [] },
          { label: '②', blanks: [blankDef(), blankDef(), blankDef()], subs: [] }
        ]}
      ]},
      { label: '', blanks: [blankDef(), blankDef(), blankDef()], subs: [] }
    ];
  }
}

export default {
  type: 'fillBlank',
  name: '填空题',
  icon: '✎',
  defaults(){
    return {
      title: '二、填空题',
      startNo: 11,
      gap: 6,
      questions: [
        { label: '', blanks: [], subs: [
          { label: '（1）', blanks: [blankDef(), blankDef()], subs: [] },
          { label: '（2）', blanks: [], subs: [
            { label: '①', blanks: [blankDef()], subs: [] },
            { label: '②', blanks: [blankDef(), blankDef(), blankDef()], subs: [] }
          ]}
        ]},
        { label: '', blanks: [blankDef(), blankDef(), blankDef()], subs: [] }
      ]
    };
  },

  configUI(container, config, onChange){
    normalize(config);
    container.innerHTML = `
      <label>标题
        <input type="text" data-k="title" value="${esc(config.title)}">
      </label>
      <label>起始题号
        <input type="number" min="1" max="200" data-k="startNo" value="${config.startNo}">
      </label>
      <label>行间距（每题之间的间距，单位 mm）
        <input type="number" min="2" max="30" data-k="gap" value="${config.gap ?? 6}">
      </label>
      <div id="fb-tree"></div>
      <button class="addbtn" data-act="add-root">+ 增加大题</button>
      <p class="hint">提示：大题可拆成多级小题（如 11（1）、11（2）①/②）；每空长度单位 mm。</p>
    `;

    const tree = container.querySelector('#fb-tree');
    const rerender = () => { renderTree(); onChange(); };

    function renderTree(){
      tree.innerHTML = '';
      config.questions.forEach((q, i) => {
        const remove = () => { config.questions.splice(i, 1); rerender(); };
        tree.appendChild(buildNode(q, 0, i, onChange, remove, rerender));
      });
    }

    container.querySelector('[data-k="title"]').addEventListener('input', e => { config.title = e.target.value; onChange(); });
    container.querySelector('[data-k="startNo"]').addEventListener('input', e => { config.startNo = parseInt(e.target.value) || 1; onChange(); });
    container.querySelector('[data-k="gap"]').addEventListener('input', e => { config.gap = parseInt(e.target.value) || 6; onChange(); });
    container.querySelector('[data-act="add-root"]').addEventListener('click', () => { config.questions.push(nodeDef(true)); rerender(); });
    renderTree();
  },

  render(config){
    normalize(config);
    const start = Math.max(1, +config.startNo || 1);
    const gap = Math.max(2, parseInt(config.gap) || 6);
    const html = config.questions.map((q, i) =>
      `<div class="fill-q" style="margin:0 0 ${gap}mm">${renderNode(q, start + i, 0)}</div>`
    ).join('');
    return `<div class="blk" style="${commonStyle(config)};--fg:${gap}mm"><div class="blk-title">${esc(config.title)}</div>${html}</div>`;
  }
};

// 递归渲染配置节点
function buildNode(node, depth, index, onChange, removeSelf, rerender){
  const card = document.createElement('div');
  card.className = 'node-card';
  card.style.cssText = `margin-top:8px;margin-left:${depth * 14}px;padding-left:8px;border-left:2px solid #cfe2f5;`;

  // 标题行：标签输入 + 删除
  const top = document.createElement('div');
  top.className = 'qrow';
  top.innerHTML = `<span>${depth === 0 ? '第 ' + (index + 1) + ' 题' : '小题 ' + (index + 1)}</span>`;
  const labelIn = document.createElement('input');
  labelIn.type = 'text';
  labelIn.value = node.label || '';
  labelIn.placeholder = depth === 0 ? '自动编号' : '例如：（1）';
  labelIn.style.flex = '1';
  labelIn.addEventListener('input', () => { node.label = labelIn.value; onChange(); });
  top.appendChild(labelIn);
  const delBtn = document.createElement('button');
  delBtn.className = 'danger';
  delBtn.textContent = '✕';
  delBtn.title = '删除本节点';
  delBtn.addEventListener('click', removeSelf);
  top.appendChild(delBtn);
  card.appendChild(top);

  // 空格列表
  const blanksWrap = document.createElement('div');
  blanksWrap.style.paddingLeft = '12px';
  node.blanks.forEach((b, bi) => {
    const row = document.createElement('div');
    row.className = 'qrow';
    row.innerHTML = `<span>空格 ${bi + 1}</span>`;
    const lenIn = document.createElement('input');
    lenIn.type = 'number';
    lenIn.min = 10; lenIn.max = 200;
    lenIn.value = b.len;
    lenIn.style.width = '80px';
    lenIn.addEventListener('input', () => { b.len = parseInt(lenIn.value) || 30; onChange(); });
    row.appendChild(lenIn);
    const del = document.createElement('button');
    del.textContent = '✕'; del.className = 'danger';
    del.addEventListener('click', () => { node.blanks.splice(bi, 1); rerender(); });
    row.appendChild(del);
    blanksWrap.appendChild(row);
  });
  card.appendChild(blanksWrap);

  // 操作按钮
  const btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:flex;gap:6px;margin-top:4px;';
  const addBlank = document.createElement('button');
  addBlank.textContent = '+ 空格';
  addBlank.addEventListener('click', () => { node.blanks.push(blankDef()); rerender(); });
  const addSub = document.createElement('button');
  addSub.textContent = '+ 小题';
  addSub.addEventListener('click', () => { if (!node.subs) node.subs = []; node.subs.push(nodeDef(false)); rerender(); });
  btnRow.append(addBlank, addSub);
  card.appendChild(btnRow);

  // 子节点
  if (node.subs && node.subs.length){
    const subWrap = document.createElement('div');
    subWrap.style.paddingLeft = '8px';
    node.subs.forEach((sub, si) => {
      const removeSub = () => { node.subs.splice(si, 1); rerender(); };
      subWrap.appendChild(buildNode(sub, depth + 1, si, onChange, removeSub, rerender));
    });
    card.appendChild(subWrap);
  }

  return card;
}

// 递归渲染预览节点（返回内联内容，外层由 render 包成 .fill-q 块，便于统一行间距）
// item 3：顶层大题的第一个小题紧跟题号内联，其余小题（如（2））才换行；更深层级（① ②）一律内联。
function renderNode(node, autoNo, depth = 0){
  const label = node.label || (depth === 0 ? (autoNo + '.') : '');
  const tag = label ? `<b>${esc(label)}</b>` : '';

  // 叶子：只有空格
  if (!(node.subs && node.subs.length)){
    const blanks = (node.blanks || []).map(b => `<span class="fill-blank" style="width:${b.len}mm"></span>`).join(' ');
    return `${tag} ${blanks}`;
  }

  // 含小题
  if (depth === 0){
    // 第一小题内联，其余小题前加换行
    const inner = node.subs.map((s, idx) => (idx === 0 ? '' : '<br>') + renderNode(s, null, depth + 1)).join('');
    return `${tag}${inner}`;
  }
  const inner = node.subs.map(s => renderNode(s, null, depth + 1)).join(' ');
  return `${tag}${inner}`;
}
