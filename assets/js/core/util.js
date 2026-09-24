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
// - 字号：作用于 .blk，子元素用 em 继承，故设一次即整体缩放
// - 对齐：text-align 给文本类元素；--jc 给 flex 容器（如考生信息栏）用 justify-content 读取
export function commonStyle(config){
  const s = [];
  if (config && config.style){
    if (config.style.fontSize) s.push(`font-size:${parseFloat(config.style.fontSize)}px`);
    if (config.style.align){
      const a = config.style.align;
      s.push(`text-align:${a}`);
      const jc = a === 'center' ? 'center' : (a === 'right' ? 'flex-end' : 'flex-start');
      s.push(`--jc:${jc}`);
    }
  }
  return s.join(';');
}
