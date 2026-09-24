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

// 图片压缩：读文件 -> canvas 等比缩放 -> dataURL（仅本地使用，绝不上传服务器）
// 回调 cb({ url, ratio })，失败回调 cb(null)
export function compressImage(file, cb, maxW = 1400, quality = 0.86){
  const reader = new FileReader();
  reader.onerror = () => cb(null);
  reader.onload = () => {
    const img = new Image();
    img.onerror = () => cb(null);
    img.onload = () => {
      const natW = img.naturalWidth || img.width;
      const natH = img.naturalHeight || img.height;
      if (!natW || !natH){ cb({ url: reader.result, ratio: 1 }); return; }
      let w = natW, h = natH;
      if (w > maxW){ h = Math.round(h * maxW / w); w = maxW; }
      let url = reader.result;
      try {
        const c = document.createElement('canvas');
        c.width = w; c.height = h;
        const ctx = c.getContext('2d');
        ctx.fillStyle = '#fff';               // JPEG 无透明通道，先铺白底
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        url = c.toDataURL('image/jpeg', quality);
      } catch(e){ /* 压缩失败则退回原图 dataURL */ }
      cb({ url, ratio: +(natW / natH).toFixed(4) });
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
}

// dataURL 估算大小(KB)
export function dataUrlKB(url){
  return Math.round((url ? url.length : 0) * 0.75 / 1024);
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
