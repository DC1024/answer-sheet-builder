// 通用工具
export function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
export function uid(){
  return 'b' + Math.random().toString(36).slice(2, 9);
}
export function deepClone(o){
  return JSON.parse(JSON.stringify(o));
}

// 通用样式字符串（字号、对齐），各题型 render 外层 .blk 可复用
export function commonStyle(config){
  const s = [];
  if (config && config.style){
    if (config.style.fontSize) s.push(`font-size:${parseFloat(config.style.fontSize)}px`);
    if (config.style.align) s.push(`text-align:${config.style.align}`);
  }
  return s.join(';');
}
