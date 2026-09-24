// 阅卷模板导出：把预览区里「每个填涂圈的圆心坐标」量出来，交给扫描识别服务定位。
// 坐标全部是「相对该面（.page 卡片）左上角」的毫米值 —— 扫描端只要用四角定位点
// 做透视矫正到同一张 mm 网格，就能按坐标直接采样，不依赖任何模型 / 训练。
import { pageGeom } from './geometry.js';
import { store } from './store.js';

const FORMAT = 'asb-omr/1';

function mmPerPx(){
  const d = document.createElement('div');
  d.style.cssText = 'width:100mm;position:absolute;left:-9999px;top:-9999px;visibility:hidden';
  document.body.appendChild(d);
  const px = d.getBoundingClientRect().width;
  d.remove();
  return px ? 100 / px : 96 / 25.4;   // mm per CSS px（兜底 96dpi）
}

// 相对某个 .page 卡片左上角的中心点（mm）
function centerMM(el, pageRect, mmpp){
  const r = el.getBoundingClientRect();
  return {
    x: +(((r.left + r.right) / 2 - pageRect.left) * mmpp).toFixed(2),
    y: +(((r.top + r.bottom) / 2 - pageRect.top) * mmpp).toFixed(2),
    w: +(r.width * mmpp).toFixed(2),
    h: +(r.height * mmpp).toFixed(2)
  };
}

/**
 * 从已渲染的预览区导出阅卷模板。
 * @param {HTMLElement} sheet 预览容器（#sheet）
 * @returns {object} 模板对象；没有可识别的填涂圈时 questions 为空数组
 */
export function exportOmrTemplate(sheet){
  const g = pageGeom();
  const mmpp = mmPerPx();
  const pages = [...sheet.querySelectorAll('.page')].map((p, idx) => {
    const pr = p.getBoundingClientRect();
    const marks = [...p.querySelectorAll('.cmark')].map(m => {
      const cls = [...m.classList].find(c => ['tl', 'tr', 'bl', 'br'].includes(c)) || 'tl';
      const c = centerMM(m, pr, mmpp);
      return { pos: cls, x: c.x, y: c.y, size: c.w };
    });
    const questions = [];
    p.querySelectorAll('.scq[data-q]').forEach(q => {
      const no = parseInt(q.dataset.q, 10);
      if (!no) return;
      const opts = [...q.querySelectorAll('.bub[data-opt]')].map(b => {
        const c = centerMM(b, pr, mmpp);
        return {
          opt: b.dataset.opt,
          x: c.x, y: c.y,
          w: +Math.max(1.2, c.w).toFixed(2),
          h: +Math.max(1.2, c.h).toFixed(2)
        };
      });
      if (!opts.length) return;                       // 手写（横线）题没有填涂圈
      const qc = centerMM(q, pr, mmpp);
      questions.push({ no, x: qc.x, y: qc.y, options: opts });
    });
    questions.sort((a, b) => a.no - b.no);
    return { index: idx, marks, questions };
  });

  return {
    format: FORMAT,
    generatedAt: new Date().toISOString(),
    paper: {
      size: store.paper.size, orientation: store.paper.orientation || 'portrait',
      w: +g.pw.toFixed(2), h: +g.ph.toFixed(2)
    },
    marks: { style: g.markStyle, size: +g.markSize.toFixed(2) },
    pages,
    questionCount: pages.reduce((n, p) => n + p.questions.length, 0)
  };
}

export function omrTemplateFileName(tpl){
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
  return `asb-omr-template-${tpl.paper.size}-${tpl.questionCount}q-${stamp}.json`;
}
