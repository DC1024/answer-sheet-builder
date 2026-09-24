// 轻量 UI 状态：只存在于运行期，不属于模板数据，不进 JSON 导出 / localStorage 语义
// 目前只用于「解答题当前指向第几题」——预览区悬停 / 点选作答区会更新它，
// 属性面板据此高亮对应题卡，Ctrl+V 粘贴图片时也据此决定贴到哪一题。
export const ui = { ansId: null, ansQ: 0 };

export function setAnsTarget(id, qi){
  ui.ansId = id;
  ui.ansQ = Math.max(0, qi | 0);
}

export function ansTargetFor(id){
  return ui.ansId === id ? Math.max(0, ui.ansQ | 0) : 0;
}

export function clearAnsTarget(id){
  if (ui.ansId === id){ ui.ansId = null; ui.ansQ = 0; }
}
