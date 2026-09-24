// 主程序：装配面板、结构列表、属性面板、预览、打印
import { store } from './core/store.js';
import { registry } from './core/registry.js';
import { renderPreview } from './core/preview.js';
import { uid, deepClone, compressImage, mmPx } from './core/util.js';

let dragId = null;
let dropTarget = null;
let clipBlock = null;            // 应用内复制的模块（Ctrl+C / Ctrl+X）

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

/* ---------- 轻提示 ---------- */
let toastTimer = null;
function toast(msg){
  let el = document.getElementById('toast');
  if (!el){
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 1600);
}

/* ---------- 剪贴板 / 快捷键 ---------- */
function isTextField(el){
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

function copySelected(){
  const b = store.getBlock(store.selectedId);
  if (!b) return false;
  clipBlock = deepClone({ type: b.type, config: b.config });
  toast('已复制：' + ((registry.get(b.type) || {}).name || b.type));
  return true;
}

function cutSelected(){
  const b = store.getBlock(store.selectedId);
  if (!b) return false;
  clipBlock = deepClone({ type: b.type, config: b.config });
  store.removeBlock(b.id);
  toast('已剪切：' + ((registry.get(b.type) || {}).name || b.type));
  return true;
}

// 粘贴：① 剪贴板里有图片且当前选中「图片」模块 → 贴图；② 应用内复制过模块 → 插到其后；
//       ③ 剪贴板文本是单个模块 JSON → 也直接插入
function pasteFromEvent(ev){
  const dt = ev.clipboardData;
  if (!dt) return false;

  const sel = store.getBlock(store.selectedId);

  if (dt.items){
    for (const it of dt.items){
      if (it.kind === 'file' && /^image\//.test(it.type)){
        if (sel && sel.type === 'image'){
          const f = it.getAsFile();
          if (f){
            compressImage(f, ok => {
              if (!ok) return;
              sel.config.src = ok.url;
              sel.config.ratio = ok.ratio;
              store.commit('paste-img');
              store.emit();
              toast('图片已粘贴（本地压缩，仅存浏览器缓存）');
            });
            return true;
          }
        }
        toast('图片需选中「图片」模块后才能粘贴');
        return true;
      }
    }
  }

  const insertAt = () => {
    const idx = store.blocks.findIndex(b => b.id === store.selectedId);
    return idx < 0 ? store.blocks.length : idx + 1;
  };

  if (clipBlock){
    store.insertBlock(insertAt(), clipBlock);
    toast('已粘贴模块');
    return true;
  }

  const text = dt.getData('text/plain');
  if (text){
    try {
      const d = JSON.parse(text);
      if (d && typeof d === 'object' && d.type && registry.get(d.type)){
        store.insertBlock(insertAt(), { type: d.type, config: d.config || {} });
        toast('已从剪贴板粘贴模块');
        return true;
      }
    } catch(e){ /* 不是 JSON，交给浏览器默认行为 */ }
  }
  return false;
}

function doUndo(){ const ok = store.undo(); if (ok) toast('已撤销'); return ok; }
function doRedo(){ const ok = store.redo(); if (ok) toast('已重做'); return ok; }

function bindShortcuts(){
  document.addEventListener('keydown', e => {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod) return;
    const k = (e.key || '').toLowerCase();
    // 文本框 / 下拉框内：一律交给浏览器原生处理（光标、文本撤销、文本粘贴）
    if (isTextField(document.activeElement)) return;

    if (k === 'z' && !e.shiftKey){ if (doUndo()) e.preventDefault(); return; }
    if ((k === 'z' && e.shiftKey) || k === 'y'){ if (doRedo()) e.preventDefault(); return; }
    if (k === 'c'){ if (copySelected()) e.preventDefault(); return; }
    if (k === 'x'){ if (cutSelected()) e.preventDefault(); return; }
  });

  // 粘贴走 paste 事件：keydown 上拿不到 clipboardData
  document.addEventListener('paste', e => {
    if (isTextField(document.activeElement)) return;
    if (pasteFromEvent(e)) e.preventDefault();
  });
}

function syncUndoButtons(){
  const u = document.getElementById('btn-undo');
  const r = document.getElementById('btn-redo');
  if (u) u.disabled = !store.canUndo();
  if (r) r.disabled = !store.canRedo();
}

/* ---------- 轻量更新（配置编辑时，不重建属性面板以保焦点） ---------- */
function liveUpdate(){
  const b = store.getBlock(store.selectedId);
  if (b){
    const el = document.querySelector(`.struct-item[data-id="${b.id}"] .nm`);
    if (el) el.textContent = blockLabel(b);
    // 记录撤销点：同一次连续输入会被合并成一步（见 store.commit 的 label 合并）
    store.commit('config:' + b.id);
  }
  renderPreviewAndGuides();
  syncUndoButtons();
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

/* ---------- 纸张控件回填（撤销/重做后需要同步 UI） ---------- */
function syncPaperControls(){
  const sizeSel = document.getElementById('paper-size');
  const orientSel = document.getElementById('paper-orient');
  const marksSel = document.getElementById('paper-marks');
  const markSizeIn = document.getElementById('mark-size');
  if (sizeSel) sizeSel.value = store.paper.size;
  if (orientSel) orientSel.value = store.paper.orientation;
  if (marksSel) marksSel.value = store.paper.marks || 'square';
  if (markSizeIn) markSizeIn.value = store.paper.markSize || 4;
}

/* ---------- 预览内直接拖动解答题作答区的下边缘调高度 ---------- */
// 拖动过程只改 DOM 的 height（不重渲染），松手才写回 config 并记一个撤销点 ——
// 重渲染会换掉 DOM 节点，拖动中重渲染等于把把手从指针下抽走。
const ANSWER_H_MIN = 40, ANSWER_H_MAX = 400;
let rzState = null;

function bindResizers(){
  const sheet = document.getElementById('sheet');

  // 事件委托：把手每次重渲染都会重建，委托到常驻的 #sheet 上只绑一次
  sheet.addEventListener('pointerdown', e => {
    if (e.button > 0) return;
    const grip = e.target.closest && e.target.closest('.rz-grip');
    if (!grip) return;
    const ab = grip.closest('.ab');
    if (!ab) return;
    const b = store.getBlock(ab.dataset.blk);
    const qi = parseInt(ab.dataset.qi, 10);
    if (!b || !b.config.questions || !b.config.questions[qi]) return;

    e.preventDefault();
    e.stopPropagation();
    const startH = Math.max(ANSWER_H_MIN, Math.min(ANSWER_H_MAX, +b.config.questions[qi].h || 120));
    rzState = { grip, ab, id: b.id, qi, startY: e.clientY, startH, h: startH };
    document.body.classList.add('rz-drag');
    grip.classList.add('on');
    const tag = grip.querySelector('.rz-tag');
    if (tag) tag.textContent = Math.round(startH) + 'mm';
  });

  window.addEventListener('pointermove', e => {
    const s = rzState;
    if (!s) return;
    // 1 CSS px = 1/mmPx() mm（预览区 1:1 显示，无缩放变换）
    const h = Math.max(ANSWER_H_MIN, Math.min(ANSWER_H_MAX, s.startH + (e.clientY - s.startY) / mmPx()));
    s.h = h;
    s.ab.style.height = h.toFixed(1) + 'mm';
    const tag = s.grip.querySelector('.rz-tag');
    if (tag) tag.textContent = Math.round(h) + 'mm';
  });

  const end = () => {
    const s = rzState;
    if (!s) return;
    const b = store.getBlock(s.id);
    rzState = null;
    document.body.classList.remove('rz-drag');
    s.grip.classList.remove('on');
    if (b && b.config.questions[s.qi]){
      b.config.questions[s.qi].h = Math.round(s.h);   // 整数 mm，与属性面板一致
      store.selectedId = s.id;
      store.commit('resize:' + s.id + ':' + s.qi);    // 一次拖动 = 一个撤销点
      fullRender();
      toast(`第 ${s.qi + 1} 题作答区高度 ${Math.round(s.h)}mm`);
    }
  };
  window.addEventListener('pointerup', end);
  window.addEventListener('pointercancel', end);
}

/* ---------- 全量渲染 ---------- */
function fullRender(){
  syncPaperControls();
  applyPaper();
  renderStructure();
  renderProps();
  renderPreviewAndGuides();
  syncUndoButtons();
}

/* ---------- 工具栏绑定 ---------- */
function bindToolbar(){
  const sizeSel = document.getElementById('paper-size');
  const orientSel = document.getElementById('paper-orient');
  sizeSel.value = store.paper.size;
  orientSel.value = store.paper.orientation;
  sizeSel.addEventListener('change', e => { store.paper.size = e.target.value; store.commit('paper'); applyPaper(); renderPreviewAndGuides(); syncUndoButtons(); });
  orientSel.addEventListener('change', e => { store.paper.orientation = e.target.value; store.commit('paper'); applyPaper(); renderPreviewAndGuides(); syncUndoButtons(); });

  // 定位点：样式 + 边长（每面只要有内容就自动加四角定位点）
  const marksSel = document.getElementById('paper-marks');
  const markSizeIn = document.getElementById('mark-size');
  marksSel.value = store.paper.marks || 'square';
  markSizeIn.value = store.paper.markSize || 4;
  marksSel.addEventListener('change', e => { store.paper.marks = e.target.value; store.commit('paper'); renderPreviewAndGuides(); syncUndoButtons(); });
  markSizeIn.addEventListener('input', e => {
    const v = parseFloat(e.target.value);
    if (!isNaN(v)) store.paper.markSize = Math.max(1, Math.min(12, v));
    store.commit('paper:markSize');
    renderPreviewAndGuides();
  });

  document.getElementById('btn-undo').addEventListener('click', doUndo);
  document.getElementById('btn-redo').addEventListener('click', doRedo);

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
  store.resetHistory();          // 初始状态作为撤销基线
  applyPaper();
  renderPalette();
  bindToolbar();
  bindShortcuts();
  bindResizers();
  fullRender();
  store.subscribe(fullRender);
  window.addEventListener('resize', renderPreviewAndGuides);
}

init();
