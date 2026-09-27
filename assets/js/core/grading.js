// 人工阅卷（主观题）配置：解答题 / 填空题共用。
//
// 为什么单独抽出来：这套配置要同时服务三处，散在各块里迟早会分叉 ——
//   1) 配置面板：满分 + 可选小问（小问模式）
//   2) render()：把 grade 落到作答区元素的 data-* 上（omr.js 只读 DOM，拿不到 config）
//   3) omr.js 导出模板：读 data-* 写进 questions[].points / subs
//
// 给分模式由「有没有小问」决定，不另设开关：
//   subs 为空 → 按题给分（0 ~ points，支持小数）
//   有 subs   → 按小问分别给分再汇总（每个小问 0 ~ 各自满分）
// 这条规则与扫描端 scoring.py 的判法是同一条，两边必须一致。

const num = v => { const n = parseFloat(v); return Number.isFinite(n) && n > 0 ? n : 0; };

// 题号：配置节点上可能叫 points / subs，缺失就补默认值（旧模板兼容）
//
// ⚠️ subs 一律**就地**规整，绝不 `.map()` 成新对象：
// 填空题把「大题 → 小题 → 小小题」整棵树都存在 subs 上（节点里还有 blanks / 更深一层
// subs）。早先这里用 `.map(s => ({label, points}))` 重建对象，等于把 blanks 和下一层
// 整个丢掉 —— 表现是打开填空题配置面板直接抛
// `Cannot read properties of undefined (reading 'forEach')`（深层节点没了 blanks）。
// 导出前由 gradeSubs() 收敛成干净的 {label, points}，所以导出格式不受影响。
export function normalizeGrade(node){
  if (!node || typeof node !== 'object') return node;
  node.points = num(node.points);
  if (!Array.isArray(node.subs)) node.subs = [];
  node.subs = node.subs.filter(s => s && typeof s === 'object');
  node.subs.forEach(s => {
    s.label = String(s.label == null ? '' : s.label);
    s.points = num(s.points);
  });
  return node;
}

// 是否纳入人工阅卷：本題设了满分，或有任何一个小问设了满分
export function gradeOn(node){
  normalizeGrade(node);
  return node.points > 0 || node.subs.some(s => s.points > 0);
}

// 该题的总满分：直接给的就是 points；只配了小问就取小问之和
export function gradeTotalPoints(node){
  normalizeGrade(node);
  if (node.points > 0) return node.points;
  return node.subs.reduce((n, s) => n + s.points, 0);
}

// 该题有效的小问列表（只留分值 > 0 的，空小问不发给扫描端）
export function gradeSubs(node){
  normalizeGrade(node);
  return node.subs.filter(s => s.points > 0).map(s => ({ label: s.label, points: s.points }));
}

const attrEsc = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * 生成挂在作答区元素上的 data-*（omr.js 读它导出模板）。
 * 不纳入人工阅卷时返回空串 —— 扫描端据此完全忽略这一块。
 */
export function gradeAttrs(node){
  if (!gradeOn(node)) return '';
  const pts = gradeTotalPoints(node);
  const subs = gradeSubs(node);
  let s = ` data-region-points="${pts}"`;
  if (subs.length) s += ` data-region-subs="${attrEsc(JSON.stringify(subs))}"`;
  return s;
}

/**
 * 配置面板里的「人工阅卷」区块 HTML（满分 + 小问编辑）。
 * @param node 题目配置对象（会被就地修改）
 * @param ctx  { rebind: fn, onChange: fn, label: string }
 *             rebind  = 小问增删后需要重新绑定事件；（由调用方提供）
 */
export function gradeConfigHTML(node, ctx){
  normalizeGrade(node);
  const label = (ctx && ctx.label) || '本题';
  const subs = node.subs.map((s, i) => `
    <div class="qrow" data-subrow="${i}">
      <label style="margin:0;flex:1;">小问名
        <input type="text" data-sub-label="${i}" value="${attrEsc(s.label)}" placeholder="如：（1）">
      </label>
      <label style="margin:0;">满分
        <input type="number" min="0" max="200" step="0.5" data-sub-points="${i}" value="${s.points}">
      </label>
      <button class="danger" data-sub-del="${i}" title="删除这个小问">✕</button>
    </div>`).join('');
  return `
    <div class="grade-box">
      <div class="qrow">
        <label style="margin:0;">${attrEsc(label)}满分
          <input type="number" min="0" max="200" step="0.5" data-g-points
            value="${node.points}" title="填 0 表示不纳入人工阅卷">
        </label>
        <button data-sub-add title="增加一个小问，按小问分别给分">+ 小问</button>
      </div>
      ${subs}
      <p class="hint" style="margin:2px 0 0;">
        <b>满分填 0 = 不纳入阅卷</b>。不设小问时按「整题一个分数」给分；
        设了小问则按小问分别给分再自动汇总，扫描端的作答区仍是一整块。
      </p>
    </div>`;
}

/**
 * 把「人工阅卷」区块的事件绑上。调用方在 renderList()/renderTree() 之后调一次。
 * @param scope  区块所在的容器（会用 querySelector 找 data-*）
 */
export function bindGrade(scope, node, opts){
  const onChange = (opts && opts.onChange) || (() => {});
  const rerender = (opts && opts.rerender) || (() => {});
  normalizeGrade(node);
  const gp = scope.querySelector('[data-g-points]');
  if (gp) gp.addEventListener('input', () => { node.points = num(gp.value); onChange(); });
  scope.querySelectorAll('[data-sub-label]').forEach(inp => inp.addEventListener('input', () => {
    node.subs[+inp.dataset.subLabel].label = inp.value; onChange();
  }));
  scope.querySelectorAll('[data-sub-points]').forEach(inp => inp.addEventListener('input', () => {
    node.subs[+inp.dataset.subPoints].points = num(inp.value); onChange();
  }));
  scope.querySelectorAll('[data-sub-del]').forEach(b => b.addEventListener('click', () => {
    node.subs.splice(+b.dataset.subDel, 1); rerender(); onChange();
  }));
  const add = scope.querySelector('[data-sub-add]');
  if (add) add.addEventListener('click', () => {
    node.subs.push({ label: '', points: 0 }); rerender(); onChange();
  });
}
