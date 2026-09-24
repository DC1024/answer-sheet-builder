// 纸张 / 版心几何：全项目单一来源。
// 分页引擎（preview.js）与所有「按可用宽度自适应」的题型（选择题列数、考号填涂区）
// 都必须从这里取尺寸 —— 否则一旦页边距变化，各处算出的可用宽度就会不一致，
// 表现为「按估算排完却仍然折行 / 溢出」。
import { store } from './store.js';
import { mmPx } from './util.js';

export const PAPER = { A3: { w: 297, h: 420 }, A4: { w: 210, h: 297 } };
export const COL_GAP_MM = 6;      // A3 双栏的栏间距
export const MARK_INSET = 3;      // 定位点距纸张边缘(mm)
export const MARK_CLEAR = 1;      // 定位点与内容区之间的最小空隙(mm)
export const MIN_PAD_X = 7;       // 无定位点时的基础页内边距
export const MIN_PAD_Y = 6;

// 定位点设置（含默认值与范围钳制）
export function markConfig(){
  const style = store.paper.marks || 'none';
  const size = Math.max(1, Math.min(12, +(store.paper.markSize || 4)));
  return { style, size };
}

// 一面的几何信息。关键点：页内边距由「定位点占用的页边距带」反推，
// 保证定位点始终落在页边距内、绝不覆盖内容。
export function pageGeom(){
  const { size: paperSize, orientation } = store.paper;
  const dim = PAPER[paperSize] || PAPER.A4;
  let pw = dim.w, ph = dim.h;
  if (orientation === 'landscape') [pw, ph] = [ph, pw];

  const { style: markStyle, size: markSize } = markConfig();
  const reserve = markStyle === 'none' ? 0 : MARK_INSET + markSize + MARK_CLEAR;
  const padX = Math.max(MIN_PAD_X, reserve);
  const padY = Math.max(MIN_PAD_Y, reserve);

  const contentW = pw - padX * 2;
  const contentH = ph - padY * 2;
  const cols = paperSize === 'A3' ? 2 : 1;          // A3 每面双栏 / A4 单栏
  const colW = cols > 1 ? (contentW - COL_GAP_MM) / 2 : contentW;

  return { pw, ph, padX, padY, contentW, contentH, cols, colW, markStyle, markSize, reserve };
}

// 单个题型区块（.blk）内部真正可用的宽度(mm)。
// .blk 有左右各 10px padding + 1.5px 边框，必须扣掉，否则排版会宽出 6mm 左右而折行。
export function blockInnerMM(){
  const px = mmPx();
  return pageGeom().colW - 2 * (10 + 1.5) / px;
}
