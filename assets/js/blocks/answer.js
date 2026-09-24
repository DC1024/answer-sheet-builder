// 模块：解答题（可设作答区高度；可选「横线」样式；每题可插入图片）
import { esc, commonStyle, compressImage, dataUrlKB } from '../core/util.js';

const MAX_INPUT = 20 * 1024 * 1024;

export default {
  type: 'answer',
  name: '解答题',
  icon: '📐',
  defaults: () => ({
    title: '三、解答题',
    startNo: 13,
    lined: false,
    lineGap: 8,
    questions: [ { h: 160, img: '', ratio: 0, imgW: 60 } ]
  }),

  configUI(container, config, onChange){
    config.questions.forEach(q => {
      if (q.img === undefined) q.img = '';
      if (q.ratio === undefined) q.ratio = 0;
      if (q.imgW === undefined) q.imgW = 60;
    });
    container.innerHTML = `
      <label>标题
        <input type="text" data-k="title" value="${esc(config.title)}">
      </label>
      <label>起始题号
        <input type="number" min="1" max="200" data-k="startNo" value="${config.startNo}">
      </label>
      <label>作答区样式
        <select data-k="lined">
          <option value="false">空白</option>
          <option value="true">横线</option>
        </select>
      </label>
      <label>横线间距(mm)
        <input type="number" min="4" max="20" data-k="lineGap" value="${config.lineGap ?? 8}">
      </label>
      <p class="hint">横线间距仅在「横线」样式下生效。每题的「作答区高度」单位 mm。每题可选插一张图片（题干图），上传即本地压缩、仅存浏览器缓存。</p>
      <div class="qlist" id="ans-list"></div>
      <button class="addbtn" data-act="add">+ 增加一题</button>
    `;
    const list = container.querySelector('#ans-list');

    const renderList = () => {
      list.innerHTML = config.questions.map((q, i) => `
        <div class="qcard">
          <div class="qrow">
            <span>第 ${i + 1} 题</span>
            <label style="margin:0;">作答区高度(mm)
              <input type="number" min="40" max="400" data-i="${i}" data-f="h" value="${q.h}">
            </label>
            <button data-del="${i}" class="danger">✕</button>
          </div>
          <div class="qrow" style="align-items:center;">
            <label style="margin:0;flex:1;">图片
              <input type="file" accept="image/*" data-img="${i}">
            </label>
          </div>
          <div class="qrow">
            <label style="margin:0;">图片宽(%)
              <input type="number" min="5" max="100" data-imgw="${i}" value="${q.imgW ?? 60}">
            </label>
            <button data-imgclear="${i}">清除图片</button>
          </div>
          ${q.img ? `<div class="img-thumb"><img src="${q.img}" alt=""></div>
            <p class="hint" style="margin:2px 0 0;">已插入图片（约 ${dataUrlKB(q.img)} KB）</p>` : ''}
        </div>`).join('');

      list.querySelectorAll('[data-f="h"]').forEach(inp => inp.addEventListener('input', e => {
        config.questions[+e.target.dataset.i].h = parseInt(e.target.value) || 80; onChange();
      }));
      list.querySelectorAll('[data-imgw]').forEach(inp => inp.addEventListener('input', e => {
        config.questions[+e.target.dataset.imgw].imgW = Math.max(5, Math.min(100, parseInt(e.target.value) || 60)); onChange();
      }));
      list.querySelectorAll('[data-img]').forEach(inp => inp.addEventListener('change', e => {
        const i = +e.target.dataset.img;
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        if (!/^image\//.test(f.type)) return;
        if (f.size > MAX_INPUT){ alert('图片过大（>20MB），请先压缩后再试。'); e.target.value = ''; return; }
        compressImage(f, res => {
          if (!res || !res.url) return;
          config.questions[i].img = res.url;
          config.questions[i].ratio = res.ratio || 0;
          renderList(); onChange();
        });
        e.target.value = '';
      }));
      list.querySelectorAll('[data-imgclear]').forEach(b => b.addEventListener('click', e => {
        const i = +e.target.dataset.imgclear;
        config.questions[i].img = ''; config.questions[i].ratio = 0;
        renderList(); onChange();
      }));
      list.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', e => {
        config.questions.splice(+e.target.dataset.del, 1);
        if (config.questions.length === 0) config.questions.push({ h: 160, img: '', ratio: 0, imgW: 60 });
        renderList(); onChange();
      }));
    };
    renderList();

    container.querySelector('[data-act="add"]').addEventListener('click', () => {
      config.questions.push({ h: 160, img: '', ratio: 0, imgW: 60 }); renderList(); onChange();
    });
    container.querySelector('[data-k="title"]').addEventListener('input', e => { config.title = e.target.value; onChange(); });
    container.querySelector('[data-k="startNo"]').addEventListener('input', e => { config.startNo = parseInt(e.target.value) || 1; onChange(); });
    const linedSel = container.querySelector('[data-k="lined"]');
    linedSel.value = String(!!config.lined);
    linedSel.addEventListener('change', e => { config.lined = (e.target.value === 'true'); onChange(); });
    container.querySelector('[data-k="lineGap"]').addEventListener('input', e => { config.lineGap = parseInt(e.target.value) || 8; onChange(); });
  },

  render(config){
    const start = Math.max(1, +config.startNo || 1);
    const lined = !!config.lined;
    const lg = Math.max(4, parseInt(config.lineGap) || 8);
    const qs = config.questions.map((q, i) => {
      const h = Math.max(40, +q.h || 120);
      const abCls = lined ? 'ab lined' : 'ab';
      const abStyle = `height:${h}mm;` + (lined ? `--lg:${lg}mm` : '');
      const imgW = Math.max(5, Math.min(100, +q.imgW || 60));
      const imgHtml = q.img
        ? `<div class="ans-img" style="text-align:center"><img class="img-el" src="${q.img}" style="width:${imgW}%;${(+q.ratio > 0) ? `aspect-ratio:${q.ratio};` : ''}"></div>`
        : '';
      return `<div class="ans-box">
        <div class="ah">${start + i}.</div>${imgHtml}<div class="${abCls}" style="${abStyle}"></div></div>`;
    }).join('');
    return `<div class="blk" style="${commonStyle(config)}"><div class="blk-title">${esc(config.title)}</div>${qs}</div>`;
  }
};
