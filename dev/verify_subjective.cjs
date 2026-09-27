// 端到端验证（第 1 步，制卡端）：制卡端「人工阅卷（主观题）」配置 → 导出模板。
//
// 打开真实 app.html，构造 选择题 + 填空题 + 解答题 三个块，给其中几道题填满分 / 小问，
// exportOmrTemplate() 导出模板到 dev/.cache/subjective_template.json，并断言：
//   1) 勾了「人工阅卷」的题才进模板（满分填 0 的题一个都不许混进来）
//   2) questions[] 带 region（整题一块的作答区坐标，mm）+ points + subs
//   3) 解答题的整体区域够高够宽（它是「整题一块」，不是一条线）
//
// 第 2 步（扫描端解析同一份模板）在 dev/check_subjective_template.py ——
// **为什么不在这一个脚本里顺手调 Python**：node 起子进程在本机沙箱里会 EBUSY
// （连 cmd.exe 都起不来），所以在 CI/沙箱里那样写会变成一个「看起来跑了其实没跑」的假绿。
// 两步分开就永远是诚实的。
//
// 依赖（仅开发用）：playwright-core + 一个 Chromium 可执行文件。
// 用法：
//   python -m http.server 8123                       # 仓库根目录起静态服务
//   NODE_PATH=<node_modules> node dev/verify_subjective.cjs
//   PY=scanner/.venv/Scripts/python.exe python dev/check_subjective_template.py
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE || 'http://127.0.0.1:8123';
const URL = BASE + '/app.html';
const ROOT = path.join(__dirname, '..');
const EXE = process.env.CHROME || path.join(process.env.LOCALAPPDATA || '', 'ms-playwright',
  'chromium-1234', 'chrome-win64', 'chrome.exe');
const CACHE = path.join(__dirname, '.cache');
const OUT = process.env.OUT || path.join(CACHE, 'subjective_template.json');

let FAILS = 0;
function assert(cond, msg, extra){
  if (!cond){ FAILS++; console.error('  ✗ ' + msg + (extra ? '  ' + extra : '')); }
  else console.log('  ✓ ' + msg + (extra ? '  ' + extra : ''));
}

(async () => {
  if (!fs.existsSync(EXE)) throw new Error('找不到 Chromium：' + EXE + '（用 CHROME= 指定）');
  const browser = await chromium.launch({ args: ['--no-sandbox'], executablePath: EXE });
  const page = await browser.newPage({ viewport: { width: 1400, height: 2200 }, deviceScaleFactor: 2 });
  const errors = [];
  const http4xx = [];
  // 只把真正的 JS 异常当失败：静态服务没有 favicon，浏览器会自动要 /favicon.ico，
  // 那条 "Failed to load resource: 404" 是环境噪音，不是页面问题 —— 混进来会让人
  // 习惯性忽略这一行，真出 JS 错误时反而看不见。
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  page.on('response', r => { if (r.status() >= 400) http4xx.push(r.status() + ' ' + r.url()); });
  await page.goto(URL, { waitUntil: 'load' });
  if (http4xx.length) console.log('  （环境提示，非失败）静态服务的 4xx：' + http4xx.join(' | '));

  console.log('=== A. 构造「选择题 + 填空题 + 解答题」并渲染 ===');
  const built = await page.evaluate(async () => {
    const store = (await import('/assets/js/core/store.js')).store;
    const registry = (await import('/assets/js/core/registry.js')).registry;
    store.blocks = [];

    // 选择题：1-6（客观题，不参与人工阅卷）
    const sc = registry.get('singleChoice').defaults();
    sc.title = '一、选择题';
    sc.startNo = 1; sc.count = 6; sc.options = 4;
    store.addBlock('singleChoice', sc);

    // 填空题 7（小问给分 3 + 4 = 7）、8（不阅卷）
    const fb = registry.get('fillBlank').defaults();
    fb.title = '二、填空题';
    fb.startNo = 7;
    fb.questions[0].points = 0;                 // 整题不给分 → 只按小问汇总
    fb.questions[0].subs[0].points = 3;         // 小题（1）3 分
    fb.questions[0].subs[1].points = 4;         // 小题（2）4 分
    fb.questions[1].points = 0;                 // 不纳入阅卷
    store.addBlock('fillBlank', fb);

    // 解答题 9（整题 + 小问都有）、10（不阅卷）
    const ans = registry.get('answer').defaults();
    ans.title = '三、解答题';
    ans.startNo = 9;
    ans.questions = [
      { h: 160, img: '', ratio: 0, imgW: 60, imgPos: 'mc',
        points: 10, subs: [{ label: '（1）', points: 4 }, { label: '（2）', points: 6 }] },
      { h: 100, img: '', ratio: 0, imgW: 60, imgPos: 'mc', points: 0, subs: [] },
    ];
    store.addBlock('answer', ans);
    return { blocks: store.blocks.length, types: store.blocks.map(b => b.type) };
  });
  console.log('  构造:', JSON.stringify(built));
  assert(built.blocks === 3, '三个块都加上了', JSON.stringify(built.types));

  await page.evaluate(() => window.dispatchEvent(new Event('resize')));
  await page.waitForTimeout(400);

  console.log('\n=== B. 导出模板：只有勾了「人工阅卷」的题进来 ===');
  const tpl = await page.evaluate(async () => {
    const { exportOmrTemplate } = await import('/assets/js/core/omr.js');
    const t = exportOmrTemplate(document.getElementById('sheet'));
    t._regions = document.querySelectorAll('#sheet [data-region]').length;
    t._graded = document.querySelectorAll('#sheet [data-region-points]').length;
    return t;
  });
  assert(errors.length === 0, '无页面 JS 错误', errors[0] || '');
  // 作答区元素 = 填空题 2 个大题 + 解答题 2 题（不阅卷的那两块也带 data-region，
  // 但没带 data-region-points，导出时会被 omr.js 按「满分 0」丢掉）
  assert(tpl._regions === 4, '预览里有 4 个作答区（填空题 2 + 解答题 2）', '实测 ' + tpl._regions);
  assert(tpl._graded === 2, '其中只有 2 个标了「人工阅卷」（填空题7 + 解答题9）',
    '实测 ' + tpl._graded);

  const qs = (tpl.pages || []).flatMap(p => p.questions || []);
  const regioned = qs.filter(q => q.region);
  const nums = regioned.map(q => q.no).sort((a, b) => a - b);
  assert(nums.join(',') === '7,9', '模板里带作答区的只有第 7、9 题（0 分的不混进来）',
    '实测 ' + nums.join(','));
  assert(qs.filter(q => q.options).length === 6, '6 道选择题照旧导出成填涂圈',
    '实测 ' + qs.filter(q => q.options).length);
  assert(!qs.some(q => q.no === 8 || q.no === 10), '不阅卷的题不进模板',
    '实测题号 ' + qs.map(q => q.no).join(','));

  const q7 = regioned.find(q => q.no === 7);
  const q9 = regioned.find(q => q.no === 9);
  assert(q7 && q7.points === 7, '填空题 7 的满分 = 小问之和 3+4 = 7', JSON.stringify(q7 && q7.points));
  assert(q7 && q7.subs && q7.subs.length === 2
    && q7.subs[0].points === 3 && q7.subs[1].points === 4,
    '填空题 7 的逐小问满分带上了', JSON.stringify(q7 && q7.subs));
  assert(q7.subs.every(s => s.label), '小问名用自动编号补上了（不能是空串）',
    JSON.stringify(q7.subs.map(s => s.label)));
  assert(q9 && q9.points === 10, '解答题 9 满分 10', JSON.stringify(q9 && q9.points));
  assert(q9 && q9.subs && q9.subs.map(s => s.points).join(',') === '4,6',
    '解答题 9 的逐小问满分 4/6', JSON.stringify(q9 && q9.subs));

  for (const q of regioned){
    const r = q.region;
    assert(r && ['x', 'y', 'w', 'h'].every(k => typeof r[k] === 'number' && isFinite(r[k])),
      `第 ${q.no} 题作答区坐标是 4 个有限数`, JSON.stringify(r));
    assert(r.w > 3 && r.h > 3, `第 ${q.no} 题作答区宽高都 > 3mm（不是退化成一条线）`,
      `w=${r.w} h=${r.h}`);
  }
  assert(q9.region.h > 100, '解答题整体区域够高（整题一块，不是只盖住第一行）',
    '实测 h=' + q9.region.h + 'mm');
  assert(q9.region.w > 100, '解答题区域横跨版心（整题一块）', '实测 w=' + q9.region.w + 'mm');
  assert(q9.region.y > q7.region.y, '第 9 题的区域在第 7 题下方（纵坐标单调，没串位）',
    `y7=${q7.region.y} y9=${q9.region.y}`);

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(tpl, null, 2), 'utf8');
  console.log('  模板已写', OUT);
  await browser.close();

  console.log();
  if (FAILS){ console.error(`⚠️  ${FAILS} 项未通过`); process.exit(1); }
  console.log('🎉 制卡端主观题配置 → 模板导出 全部通过');
  console.log('   下一步（扫描端解析同一份模板）：');
  console.log(`   scanner/.venv/Scripts/python.exe dev/check_subjective_template.py`);
})().catch(e => { console.error(e); process.exit(1); });
