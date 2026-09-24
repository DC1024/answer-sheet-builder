// 应用状态：答题卡结构（blocks 数组）+ 纸张设置 + 选中态
import { uid, deepClone } from './util.js';

const STORAGE_KEY = 'answer-sheet-builder.v1';

export const store = {
  paper: { size: 'A3', orientation: 'portrait' },
  blocks: [],
  selectedId: null,
  _subs: [],

  subscribe(fn){ this._subs.push(fn); },
  emit(){ this._subs.forEach(f => f()); },

  addBlock(type, config){
    const b = { id: uid(), type, config: config || {} };
    this.blocks.push(b);
    this.selectedId = b.id;
    this.emit();
    return b;
  },
  removeBlock(id){
    this.blocks = this.blocks.filter(b => b.id !== id);
    if (this.selectedId === id) this.selectedId = null;
    this.emit();
  },
  duplicateBlock(id){
    const i = this.blocks.findIndex(b => b.id === id);
    if (i < 0) return;
    const copy = { id: uid(), type: this.blocks[i].type, config: deepClone(this.blocks[i].config) };
    this.blocks.splice(i + 1, 0, copy);
    this.selectedId = copy.id;
    this.emit();
  },
  moveBlock(id, dir){
    const i = this.blocks.findIndex(b => b.id === id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= this.blocks.length) return;
    const arr = this.blocks;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    this.emit();
  },
  reorder(fromId, toId, after){
    const from = this.blocks.findIndex(b => b.id === fromId);
    if (from < 0) return;
    const [item] = this.blocks.splice(from, 1);
    let to = this.blocks.findIndex(b => b.id === toId);
    if (to < 0){ this.blocks.push(item); }
    else { this.blocks.splice(after ? to + 1 : to, 0, item); }
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
        this.paper = data.paper || this.paper;
        this.blocks = data.blocks;
        this.selectedId = null;
        return true;
      }
    } catch(e){}
    return false;
  },
  import(data){
    if (data && Array.isArray(data.blocks)){
      this.paper = data.paper || this.paper;
      this.blocks = data.blocks;
      this.selectedId = null;
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
    this.emit();
  }
};
