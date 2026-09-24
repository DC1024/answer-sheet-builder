// 主程序：装配面板、结构列表、属性面板、预览、打印
import { store } from './core/store.js';
import { registry } from './core/registry.js';
import { renderPreview } from './core/preview.js';
import { uid } from './core/util.js';

let dragId = null;
let dropTarget = null;

/* ---------- 默认模板 ---------- */
function defaultBlocks(){
  const mk = (type, patch) => ({ id: uid(), type, config: Object.assign(registry.get(type).defaults(), patch || {}) });
  return [
    mk('info'),
    mk('singleChoice', { startNo: 1 }),
    mk('fillBlank', { startNo: 11 }),
    mk('answer', { startNo: 13 })
  ];
}

function blockLabel(b){
  const mod = registry.get(b.type);
  let s = mod.name;
  if (b.config.title) s += '：' + b.config.title;
  if (b.config.count) s += `（${b.config.count}题）`;
  return s;
}

/* ---------- 纸张 ---------- */
function applyPaper(){
  const { size, orientation } = store.paper;
  const dims = size === 'A3' ? { w: 297, h: 420 } : { w: 210, h: 297 };
  let w = dims.w, h = dims.h;
  if (orientation === 'landscape') [w, h] = [h, w];
  const root = document.documentElement.style;
  root.setProperty('--sheet-w', w + 'mm');
  root.setProperty('--page-h', h + 'mm');
  // 打印时每面由 .page 卡片承载，故 @page 不留外边距（卡片自带 padding）
  document.getElementById('page-css').textContent = `@page{size:${size} ${orientation};margin:0;}`;
}

/* ---------- 预览（固定分页） ---------- */
function renderPreviewAndGuides(){
  const sheet = document.getElementById('sheet');
  renderPreview(sheet);
}

/* ---------- 轻量更新（配置编辑时，不重建属性面板以保焦点） ---------- */
function liveUpdate(){
  const b = store.getBlock(store.selectedId);
  if (b){
    const el = document.querySelector(`.struct-item[data-id="${b.id}"] .nm`);
    if (el) el.textContent = blockLabel(b);
  }
  renderPreviewAndGuides();
}

/* ---------- 结构列表 ---------- */
function clearDropMarks(){
  document.querySelectorAll('.struct-item').forEach(it => it.classList.remove('drop-before', 'drop-after'));
}
function renderStructure(){
  const wrap = document.getElementById('structure');
  wrap.innerHTML = '';
  store.blocks.forEach(b => {
    const item = document.createElement('div');
    item.className = 'struct-item' + (b.id === store.selectedId ? ' sel' : '');
    item.dataset.id = b.id;
    item.draggable = true;
    item.innerHTML = `
      <span class="handle" title="拖拽排序">⠿</span>
      <span class="nm">${blockLabel(b)}</span>
      <span class="acts">
        <button data-act="up" title="上移">↑</button>
        <button data-act="down" title="下移">↓</button>
        <button data-act="dup" title="复制">⧉</button>
        <button data-act="del" class="danger" title="删除">✕</button>
      </span>`;
    item.addEventListener('click', e => { if (!e.target.closest('.acts')) store.select(b.id); });
    item.querySelector('[data-act="up"]').addEventListener('click', () => store.moveBlock(b.id, -1));
    item.querySelector('[data-act="down"]').addEventListener('click', () => store.moveBlock(b.id, 1));
    item.querySelector('[data-act="dup"]').addEventListener('click', () => store.duplicateBlock(b.id));
    item.querySelector('[data-act="del"]').addEventListener('click', () => store.removeBlock(b.id));

    item.addEventListener('dragstart', e => { dragId = b.id; item.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
    item.addEventListener('dragend', () => { dragId = null; item.classList.remove('dragging'); clearDropMarks(); });
    item.addEventListener('dragover', e => {
      e.preventDefault();
      const r = item.getBoundingClientRect();
      const after = e.clientY > r.top + r.height / 2;
      clearDropMarks();
      item.classList.add(after ? 'drop-after' : 'drop-before');
      dropTarget = { id: b.id, after };
    });
    item.addEventListener('dragleave', () => item.classList.remove('drop-before', 'drop-after'));
    item.addEventListener('drop', e => {
      e.preventDefault();
      if (dragId && dropTarget) store.reorder(dragId, dropTarget.id, dropTarget.after);
      clearDropMarks();
    });
    wrap.appendChild(item);
  });
}

/* ---------- 属性面板 ---------- */
function renderProps(){
  const wrap = document.getElementById('props');
  const b = store.getBlock(store.selectedId);
  if (!b){ wrap.innerHTML = '<p class="hint">在左侧添加一个题型，或在结构列表中选择一个模块进行设置。</p>'; return; }
  const mod = registry.get(b.type);
  wrap.innerHTML = '';
  const head = document.createElement('div');
  head.style.cssText = 'font-weight:700;margin-bottom:10px;color:#334;';
  head.textContent = `${mod.icon} ${mod.name} 设置`;
  wrap.appendChild(head);
  const form = document.createElement('div');
  wrap.appendChild(form);
  mod.configUI(form, b.config, liveUpdate);

  // 通用样式：字号 + 对齐（作用于该模块整体）
  const styleWrap = document.createElement('div');
  styleWrap.style.cssText = 'margin-top:16px;padding-top:12px;border-top:1px solid #e6eaef;';
  styleWrap.innerHTML = `
    <div style="font-weight:700;margin-bottom:8px;color:#334;">通用样式</div>
    <div class="row">
      <label>字号(px)
        <input type="number" min="8" max="32" data-cs="fontSize" value="${b.config.style?.fontSize || ''}" placeholder="默认">
      </label>
      <label>对齐
        <select data-cs="align">
          <option value="">默认</option>
          <option value="left">左对齐</option>
          <option value="center">居中</option>
          <option value="right">右对齐</option>
        </select>
      </label>
    </div>`;
  styleWrap.querySelector('[data-cs="align"]').value = b.config.style?.align || '';
  // 防御：部分题型的 config.style 历史上被当作字符串用，这里强制归一为对象，避免严格模式抛 TypeError
  if (!b.config.style || typeof b.config.style !== 'object') b.config.style = {};
  styleWrap.querySelectorAll('[data-cs]').forEach(el => {
    const ev = el.tagName === 'SELECT' ? 'change' : 'input';
    el.addEventListener(ev, () => {
      const k = el.dataset.cs;
      let v = el.value;
      if (el.type === 'number') v = (v === '' || isNaN(parseInt(v))) ? '' : parseInt(v);
      if (v === '' || v === null) delete b.config.style[k];
      else b.config.style[k] = v;
      liveUpdate();
    });
  });
  wrap.appendChild(styleWrap);
}

/* ---------- 题型面板 ---------- */
function renderPalette(){
  const wrap = document.getElementById('palette');
  wrap.innerHTML = '';
  registry.list().forEach(mod => {
    const btn = document.createElement('button');
    btn.className = 'pbtn';
    btn.innerHTML = `<span class="ic">${mod.icon}</span><span>${mod.name}</span>`;
    btn.addEventListener('click', () => store.addBlock(mod.type, mod.defaults()));
    wrap.appendChild(btn);
  });
}

/* ---------- 全量渲染 ---------- */
function fullRender(){
  renderStructure();
  renderProps();
  renderPreviewAndGuides();
}

/* ---------- 工具栏绑定 ---------- */
function bindToolbar(){
  const sizeSel = document.getElementById('paper-size');
  const orientSel = document.getElementById('paper-orient');
  sizeSel.value = store.paper.size;
  orientSel.value = store.paper.orientation;
  sizeSel.addEventListener('change', e => { store.paper.size = e.target.value; applyPaper(); renderPreviewAndGuides(); });
  orientSel.addEventListener('change', e => { store.paper.orientation = e.target.value; applyPaper(); renderPreviewAndGuides(); });

  // 定位点：样式 + 边长（每面只要有内容就自动加四角定位点）
  const marksSel = document.getElementById('paper-marks');
  const markSizeIn = document.getElementById('mark-size');
  marksSel.value = store.paper.marks || 'square';
  markSizeIn.value = store.paper.markSize || 4;
  marksSel.addEventListener('change', e => { store.paper.marks = e.target.value; renderPreviewAndGuides(); });
  markSizeIn.addEventListener('input', e => {
    const v = parseFloat(e.target.value);
    if (!isNaN(v)) store.paper.markSize = Math.max(1, Math.min(12, v));
    renderPreviewAndGuides();
  });

  document.getElementById('btn-print').addEventListener('click', () => window.print());
  document.getElementById('btn-save').addEventListener('click', () => {
    if (store.save()) alert('已保存到本地浏览器（localStorage）。图片会一并保存在本地缓存中。');
    else alert('保存失败：本地浏览器缓存空间不足（通常是图片过大或过多）。\n建议：减少图片数量、调小图片宽度，或先「导出 JSON」备份后再清理。');
  });
  document.getElementById('btn-load').addEventListener('click', () => {
    if (store.load()){ applyPaper(); fullRender(); alert('已载入本地保存的模板。'); }
    else alert('没有找到本地保存的模板。');
  });
  document.getElementById('btn-export').addEventListener('click', () => {
    const blob = new Blob([store.export()], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'answer-sheet-template.json';
    a.click();
  });
  document.getElementById('btn-import').addEventListener('click', () => document.getElementById('file-import').click());
  document.getElementById('file-import').addEventListener('change', e => {
    const f = e.target.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => { try { store.import(JSON.parse(r.result)); applyPaper(); fullRender(); } catch(err){ alert('JSON 解析失败，请检查文件格式。'); } };
    r.readAsText(f); e.target.value = '';
  });
  document.getElementById('btn-reset').addEventListener('click', () => {
    if (confirm('确定重置为默认模板？当前未保存的修改将丢失。')){ store.reset(defaultBlocks()); applyPaper(); fullRender(); }
  });
}

/* ---------- 初始化 ---------- */
function init(){
  if (!store.load()) store.reset(defaultBlocks());
  applyPaper();
  renderPalette();
  bindToolbar();
  fullRender();
  store.subscribe(fullRender);
  window.addEventListener('resize', renderPreviewAndGuides);
}

init();
