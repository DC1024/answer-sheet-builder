// 模块：图片（item 1）
// - 上传后在浏览器端压缩（限制最大宽度 + JPEG 质量），转成 dataURL 存进 config，
//   因此「保存」= 本地浏览器缓存（localStorage），不依赖、也不增加任何服务器压力。
// - 打印 / 导出 PDF 时，dataURL 会随页面一并输出，图片可见。
// - 记录宽高比(ratio)并用 CSS aspect-ratio 占位，保证分页测量与图片加载前布局都正确。
import { esc, commonStyle } from '../core/util.js';

const MAX_W = 1400;          // 压缩后最大宽度(px)
const MAX_INPUT = 20 * 1024 * 1024; // 输入上限 20MB

function compress(file, cb){
  const reader = new FileReader();
  reader.onerror = () => cb(null);
  reader.onload = () => {
    const img = new Image();
    img.onerror = () => cb(null);
    img.onload = () => {
      const natW = img.naturalWidth || img.width;
      const natH = img.naturalHeight || img.height;
      if (!natW || !natH) { cb({ url: reader.result, ratio: 1 }); return; }
      let w = natW, h = natH;
      if (w > MAX_W){ h = Math.round(h * MAX_W / w); w = MAX_W; }
      let url = reader.result;
      try {
        const c = document.createElement('canvas');
        c.width = w; c.height = h;
        const ctx = c.getContext('2d');
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, w, h);          // JPEG 无透明通道，先铺白底
        ctx.drawImage(img, 0, 0, w, h);
        url = c.toDataURL('image/jpeg', 0.86);
      } catch(e){ /* 压缩失败则退回原图 */ }
      cb({ url, ratio: +(natW / natH).toFixed(4) });
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
}

export default {
  type: 'image',
  name: '图片',
  icon: '🖼',
  defaults: () => ({ title: '', src: '', ratio: 0, width: 100, align: 'center' }),

  configUI(container, config, onChange){
    container.innerHTML = `
      <label>标题（留空则不显示）
        <input type="text" data-k="title" value="${esc(config.title || '')}" placeholder="例如：示意图 / 地图 / 材料图">
      </label>
      <label>选择图片（自动压缩，仅存本地浏览器）
        <input type="file" accept="image/*" data-k="file">
      </label>
      <div class="row">
        <label>宽度(%)
          <input type="number" min="5" max="100" data-k="width" value="${config.width ?? 100}">
        </label>
        <label>对齐
          <select data-k="align">
            <option value="left">左对齐</option>
            <option value="center">居中</option>
            <option value="right">右对齐</option>
          </select>
        </label>
      </div>
      <button class="danger" data-act="clear" style="width:100%;">清除图片</button>
      <p class="hint" id="img-hint"></p>
    `;
    const hint = container.querySelector('#img-hint');
    const setHint = (t) => { hint.textContent = t; };
    const kb = (u) => Math.round(u.length * 0.75 / 1024);
    if (config.src) setHint(`已载入图片（约 ${kb(config.src)} KB，本地缓存）。`);
    else setHint('图片会先在本机压缩，再以 dataURL 存进浏览器缓存；不上传任何服务器，打印 / 导出 PDF 时可见。');

    container.querySelector('[data-k="file"]').addEventListener('change', e => {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      if (!/^image\//.test(f.type)){ setHint('请选择图片文件。'); return; }
      if (f.size > MAX_INPUT){ setHint('图片过大（>20MB），请先压缩后再试。'); return; }
      setHint('正在压缩…');
      compress(f, res => {
        if (!res || !res.url){ setHint('图片读取失败，请换一张试试。'); return; }
        config.src = res.url;
        config.ratio = res.ratio || 0;
        setHint(`已载入（约 ${kb(res.url)} KB，已压缩，仅存本地）。`);
        onChange();
      });
      e.target.value = '';
    });
    container.querySelector('[data-k="title"]').addEventListener('input', e => { config.title = e.target.value; onChange(); });
    container.querySelector('[data-k="width"]').addEventListener('input', e => {
      config.width = Math.max(5, Math.min(100, parseInt(e.target.value) || 100)); onChange();
    });
    const al = container.querySelector('[data-k="align"]');
    al.value = config.align || 'center';
    al.addEventListener('change', e => { config.align = e.target.value; onChange(); });
    container.querySelector('[data-act="clear"]').addEventListener('click', () => {
      config.src = ''; config.ratio = 0;
      setHint('已清除图片。'); onChange();
    });
  },

  render(config){
    const title = config.title ? `<div class="blk-title">${esc(config.title)}</div>` : '';
    const w = Math.max(5, Math.min(100, +config.width || 100));
    const align = config.align || 'center';
    let body;
    if (config.src){
      const ar = (+config.ratio > 0) ? `aspect-ratio:${config.ratio};` : '';
      body = `<div class="img-wrap" style="text-align:${align}"><img class="img-el" src="${config.src}" style="width:${w}%;${ar}"></div>`;
    } else {
      body = `<div class="img-empty">未选择图片（在右侧属性面板上传；图片仅存本地）</div>`;
    }
    return `<div class="blk" style="${commonStyle(config)}">${title}${body}</div>`;
  }
};
