// 阅卷模板导出：把预览区里「每个填涂圈的圆心坐标」量出来，交给扫描识别服务定位。
// 坐标全部是「相对该面（.page 卡片）左上角」的毫米值 —— 扫描端只要用四角定位点
// 做透视矫正到同一张 mm 网格，就能按坐标直接采样，不依赖任何模型 / 训练。
//
// v2 起额外导出「考号填涂区」（考生信息栏里的 examGrid）：扫描端把它当选择题一样采样，
// 逐位取墨迹最重的数字 —— 考号就能直接从卷面上读出来，不必再往文件名里写考号。
import { pageGeom } from './geometry.js';
import { store } from './store.js';

const FORMAT = 'asb-omr/2';

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

// 考号填涂区：把每个格子收成「第几位 → 该位的 10 个数字格」
function sidOf(pageEl, pageRect, mmpp){
  const grid = pageEl.querySelector('.exam-grid[data-sid]');
  if (!grid) return null;
  const byPos = new Map();
  grid.querySelectorAll('.ebrk[data-pos][data-digit]').forEach(b => {
    const pos = parseInt(b.dataset.pos, 10);
    if (!pos) return;
    const c = centerMM(b, pageRect, mmpp);
    if (!byPos.has(pos)) byPos.set(pos, []);
    byPos.get(pos).push({
      digit: String(b.dataset.digit),
      x: c.x, y: c.y,
      w: +Math.max(1.2, c.w).toFixed(2),
      h: +Math.max(1.2, c.h).toFixed(2)
    });
  });
  if (!byPos.size) return null;
  const positions = [...byPos.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([pos, bubbles]) => ({
      pos,
      bubbles: bubbles.sort((a, b) => (+a.digit) - (+b.digit))
    }));
  return { digits: positions.length, positions };
}

/**
 * 从已渲染的预览区导出阅卷模板。
 * @param {HTMLElement} sheet 预览容器（#sheet）
 * @returns {object} 模板对象；没有填涂圈也没有考号填涂区时 questions/sid 都为空
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
    const sid = sidOf(p, pr, mmpp);
    const page = { index: idx, marks, questions };
    if (sid) page.sid = sid;                          // 没有就整个字段不出现
    return page;
  });

  const sidPages = pages.filter(p => p.sid);
  const sidDigits = sidPages.length
    ? Math.max(...sidPages.map(p => p.sid.digits))
    : 0;

  return {
    format: FORMAT,
    generatedAt: new Date().toISOString(),
    paper: {
      size: store.paper.size, orientation: store.paper.orientation || 'portrait',
      w: +g.pw.toFixed(2), h: +g.ph.toFixed(2)
    },
    marks: { style: g.markStyle, size: +g.markSize.toFixed(2) },
    // 顶层再声明一次考号位数（各面可能有各自的坐标，但位数必须一致）——
    // 扫描端据此一眼判断「这份模板能不能读考号」，不用遍历所有面
    sid: sidDigits ? { digits: sidDigits, onPages: sidPages.map(p => p.index) } : null,
    pages,
    questionCount: pages.reduce((n, p) => n + p.questions.length, 0)
  };
}

export function omrTemplateFileName(tpl){
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
  const sid = tpl.sid ? `-${tpl.sid.digits}sid` : '';
  return `asb-omr-template-${tpl.paper.size}-${tpl.questionCount}q${sid}-${stamp}.json`;
}
