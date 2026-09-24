// 模块：填空题（支持多级小题，每空可独立设置长度）
// 编号规则（分层，互不混淆）：
//   大题      11.           ← 每行一题，题号自动累加
//   小题      （1）（2）…     ← 第 1 层
//   小小题    ①②③…         ← 第 2 层
//   再深一层  a) b) c)      ← 第 3 层
// 节点的 label 留空即「自动编号」；填了内容则作为手写编号（覆盖自动值）。
import { esc, commonStyle } from '../core/util.js';

const blankDef = () => ({ len: 30 });
// label 留空 = 自动编号（旧版这里硬编码 '（1）'，导致任何层级新增小题都是（1））
const nodeDef = () => ({ label: '', blanks: [blankDef()], subs: [] });

const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';

// 按「层级 + 序号」生成自动编号，保证不同层级一眼可区分
function autoLabel(depth, i){
  if (depth <= 1) return `（${i + 1}）`;
  if (depth === 2) return CIRCLED[i] || `(${i + 1})`;
  if (depth === 3) return `${String.fromCharCode(97 + (i % 26))})`;
  return `(${i + 1})`;
}
function levelName(depth){
  return depth === 0 ? '第 %d 题' : (depth === 1 ? '小题 %d' : (depth === 2 ? '小小题 %d' : '第 %d 级'));
}

// 兼容旧模板：blanks 曾是数字；并清掉「恰好等于自动编号」的手写 label，
// 让历史模板里那批（1）（1）（1）重新走自动编号（等价内容重算，不会丢信息）。
function normalize(config){
  if (!Array.isArray(config.questions)) config.questions = [];
  config.questions = config.questions.map(q => {
    if (typeof q.blanks === 'number'){
      const n = Math.max(1, parseInt(q.blanks) || 1);
      return { label: '', blanks: Array.from({ length: n }, blankDef), subs: [] };
    }
    return q;
  });
  config.questions.forEach(q => stripAutoLabels(q.subs, 1));
  if (config.questions.length === 0){
    config.questions = [
      { label: '', blanks: [], subs: [
        { label: '', blanks: [blankDef(), blankDef()], subs: [] },
        { label: '', blanks: [], subs: [
          { label: '', blanks: [blankDef()], subs: [] },
          { label: '', blanks: [blankDef(), blankDef(), blankDef()], subs: [] }
        ]}
      ]},
      { label: '', blanks: [blankDef(), blankDef(), blankDef()], subs: [] }
    ];
  }
}
function stripAutoLabels(nodes, depth){
  if (!Array.isArray(nodes)) return;
  nodes.forEach((n, i) => {
    if (n && typeof n.label === 'string' && n.label.trim() === autoLabel(depth, i)) n.label = '';
    if (n && Array.isArray(n.subs)) stripAutoLabels(n.subs, depth + 1);
  });
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
          { label: '', blanks: [blankDef(), blankDef()], subs: [] },
          { label: '', blanks: [], subs: [
            { label: '', blanks: [blankDef()], subs: [] },
            { label: '', blanks: [blankDef(), blankDef(), blankDef()], subs: [] }
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
      <label>行间距(mm)
        <input type="number" min="2" max="30" data-k="gap" value="${config.gap ?? 6}">
      </label>
      <div id="fb-tree"></div>
      <button class="addbtn" data-act="add-root">+ 增加大题</button>
      <p class="hint">小题编号按层级自动生成：小题为（1）（2）、小小题为①②、再深为 a) b)。留空即自动编号，填内容可手写覆盖。行间距同时作用于大题之间与折行后的行距。</p>
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
    container.querySelector('[data-act="add-root"]').addEventListener('click', () => { config.questions.push(nodeDef()); rerender(); });
    renderTree();
  },

  render(config){
    normalize(config);
    const start = Math.max(1, +config.startNo || 1);
    const gap = Math.max(2, parseInt(config.gap) || 6);
    const html = config.questions.map((q, i) =>
      `<div class="fill-q">${renderNode(q, start + i, 0, i, gap)}</div>`
    ).join('');
    return `<div class="blk" style="${commonStyle(config)};--fg:${gap}mm"><div class="blk-title">${esc(config.title)}</div>${html}</div>`;
  }
};

// 递归渲染配置节点 —— 全部按「行内流式」输出：
// 一行没排满就继续往同一行放，排满才自动换行（不再强制每个小题单独占一行）。
// 每个可独立的小题包成 .fb-item（inline-block）→ 换行时整块移动，不会把「（2）+空格」拆开。
function renderNode(node, autoNo, depth, index, gap){
  const label = (node.label && node.label.trim()) ||
                (depth === 0 ? `${autoNo}.` : autoLabel(depth, index));
  const tag = label ? `<b class="fb-tag">${esc(label)}</b>` : '';
  const blanks = (node.blanks || [])
    .map(b => `<span class="fill-blank" style="width:${b.len}mm"></span>`).join('');

  const subs = (node.subs || []);
  if (!subs.length) return `<span class="fb-item">${tag}${blanks}</span>`;

  const inner = subs.map((s, i) => renderNode(s, null, depth + 1, i, gap)).join('');
  if (depth === 0){
    // 大题：题号与各小题平铺（小题之间可自由换行），整块不锁死，才能「排满一行再换行」
    return `${tag}${blanks}${inner}`;
  }
  return `<span class="fb-item">${tag}${blanks}${inner}</span>`;
}

// 递归构建配置面板的节点卡片
function buildNode(node, depth, index, onChange, removeSelf, rerender){
  const card = document.createElement('div');
  card.className = 'node-card';
  card.style.cssText = `margin-top:8px;margin-left:${depth * 14}px;padding-left:8px;border-left:2px solid #cfe2f5;`;

  const auto = autoLabel(Math.max(1, depth), index);
  const shown = (node.label && node.label.trim()) || auto;

  // 标题行：显示当前生效编号 + 手写覆盖输入 + 删除
  const top = document.createElement('div');
  top.className = 'qrow';
  top.innerHTML = `<span>${(depth === 0 ? '第 ' + (index + 1) + ' 题' : levelName(depth).replace('%d', shown))}</span>`;
  const labelIn = document.createElement('input');
  labelIn.type = 'text';
  labelIn.value = node.label || '';
  labelIn.placeholder = `自动：${auto}`;
  labelIn.title = '留空即按层级自动编号；填写则作为手写编号';
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
  addSub.textContent = depth === 0 ? '+ 小题' : '+ 小小题';
  addSub.title = '新增一层更细的编号（小题 → ①② → a)）';
  addSub.addEventListener('click', () => { if (!node.subs) node.subs = []; node.subs.push(nodeDef()); rerender(); });
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
