// 应用状态：答题卡结构（blocks 数组）+ 纸张设置 + 选中态
import { uid, deepClone } from './util.js';

const STORAGE_KEY = 'answer-sheet-builder.v1';
const HISTORY_LIMIT = 100;      // 最多保留的撤销步数
const COALESCE_MS = 700;        // 同类连续编辑（如连续打字）合并为一步的时间窗

export const store = {
  // marks：定位点样式（none / square / triangle）；markSize：定位点边长(mm)
  paper: { size: 'A3', orientation: 'portrait', marks: 'square', markSize: 4 },
  blocks: [],
  selectedId: null,
  _subs: [],

  // ---- 撤销 / 重做历史（快照式）----
  _present: null,
  _history: [],
  _future: [],
  _lastLabel: '',
  _lastTime: 0,

  subscribe(fn){ this._subs.push(fn); },
  emit(){ this._subs.forEach(f => f()); },

  _snap(){ return JSON.stringify({ paper: this.paper, blocks: this.blocks, selectedId: this.selectedId }); },

  // 重置历史基线（载入模板 / 导入 / 重置后调用：这些操作本身不再可撤销）
  resetHistory(){
    this._present = this._snap();
    this._history = [];
    this._future = [];
    this._lastLabel = '';
    this._lastTime = 0;
  },

  // 每次「会产生变更」的操作后调用。label 用于合并同类连续编辑（如逐字符输入）。
  commit(label){
    const now = this._snap();
    if (now === this._present){ return; }        // 无实际变化
    const t = Date.now();
    if (label && label === this._lastLabel && t - this._lastTime < COALESCE_MS){
      this._present = now;                        // 合并进上一步，不新增历史
      this._lastTime = t;
      return;
    }
    this._history.push(this._present);
    if (this._history.length > HISTORY_LIMIT) this._history.shift();
    this._future.length = 0;
    this._present = now;
    this._lastLabel = label || '';
    this._lastTime = t;
  },

  canUndo(){ return this._history.length > 0; },
  canRedo(){ return this._future.length > 0; },

  undo(){
    if (!this._history.length) return false;
    const prev = this._history.pop();
    this._future.push(this._present);
    this._applySnapshot(prev);
    return true;
  },

  redo(){
    if (!this._future.length) return false;
    const next = this._future.pop();
    this._history.push(this._present);
    this._applySnapshot(next);
    return true;
  },

  _applySnapshot(json){
    const d = JSON.parse(json);
    this.paper = d.paper;
    this.blocks = d.blocks;
    this.selectedId = d.selectedId;
    this._present = json;
    this._lastLabel = '';               // 撤销后不与后续编辑合并
    this._lastTime = 0;
    this.emit();
  },

  addBlock(type, config){
    const b = { id: uid(), type, config: config || {} };
    this.blocks.push(b);
    this.selectedId = b.id;
    this.commit('add');
    this.emit();
    return b;
  },
  insertBlock(index, block){
    const b = Object.assign({}, block, { id: uid() });
    this.blocks.splice(Math.max(0, Math.min(index, this.blocks.length)), 0, b);
    this.selectedId = b.id;
    this.commit('paste');
    this.emit();
    return b;
  },
  removeBlock(id){
    this.blocks = this.blocks.filter(b => b.id !== id);
    if (this.selectedId === id) this.selectedId = null;
    this.commit('remove');
    this.emit();
  },
  duplicateBlock(id){
    const i = this.blocks.findIndex(b => b.id === id);
    if (i < 0) return;
    const copy = { id: uid(), type: this.blocks[i].type, config: deepClone(this.blocks[i].config) };
    this.blocks.splice(i + 1, 0, copy);
    this.selectedId = copy.id;
    this.commit('duplicate');
    this.emit();
  },
  moveBlock(id, dir){
    const i = this.blocks.findIndex(b => b.id === id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= this.blocks.length) return;
    const arr = this.blocks;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    this.commit('move');
    this.emit();
  },
  reorder(fromId, toId, after){
    const from = this.blocks.findIndex(b => b.id === fromId);
    if (from < 0) return;
    const [item] = this.blocks.splice(from, 1);
    let to = this.blocks.findIndex(b => b.id === toId);
    if (to < 0){ this.blocks.push(item); }
    else { this.blocks.splice(after ? to + 1 : to, 0, item); }
    this.commit('reorder:' + fromId);
    this.emit();
  },
  updateConfig(id, config){
    const b = this.blocks.find(x => x.id === id);
    if (b){ b.config = config; this.emit(); }
  },
  select(id){ this.selectedId = id; this.emit(); },
  getBlock(id){ return this.blocks.find(b => b.id === id); },
  setPaper(p){ this.paper = p; this.emit(); },

  save(){
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ paper: this.paper, blocks: this.blocks }));
      return true;
    } catch(e){ return false; }
  },
  load(){
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return false;
      const data = JSON.parse(raw);
      if (data && Array.isArray(data.blocks)){
        this.paper = Object.assign({}, this.paper, data.paper || {});
        this.blocks = data.blocks;
        this.selectedId = null;
        this.resetHistory();
        return true;
      }
    } catch(e){}
    return false;
  },
  import(data){
    if (data && Array.isArray(data.blocks)){
      this.paper = Object.assign({}, this.paper, data.paper || {});
      this.blocks = data.blocks;
      this.selectedId = null;
      this.resetHistory();
      this.emit();
      return true;
    }
    return false;
  },
  export(){
    return JSON.stringify({ paper: this.paper, blocks: this.blocks }, null, 2);
  },
  reset(blocks){
    this.blocks = blocks;
    this.selectedId = null;
    this.resetHistory();
    this.emit();
  }
};
