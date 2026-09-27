// 端到端验证：制卡端导出的 writebox 模板 → 扫描端 decode_write 识别。
// 打开真实 app.html，通过动态 import 拿 store，构造一个 writebox 选择题块，
// exportOmrTemplate 导出模板，断言 questions[] 含 write 坐标；再把模板喂给
// Python 端 omr 走整条手写识别链路。
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE || 'http://127.0.0.1:8080';
const URL = BASE + '/app.html';
const ROOT = path.resolve(__dirname, '..');
const EXE = path.join(process.env.LOCALAPPDATA || '', 'ms-playwright',
  'chromium-1234', 'chrome-win64', 'chrome.exe');
// 产物一律落 dev/.cache（在 .gitignore 里），不往仓库里写 —— 之前这里写的是
// `dev/scanner/tests/fixtures/real30`，既不在 gitignore 里、又是个根本不存在的
// 目录结构（`dev/scanner/` 不是 `scanner/`），跑一次就在仓库里留下一坨脏东西。
const OUT_DIR = path.join(__dirname, '.cache', 'writebox');
const OUT_TEMPLATE = path.join(OUT_DIR, 'builder_writebox_template.json');
const OUT_SHEET = path.join(OUT_DIR, 'builder_writebox_sheet.png');

function assert(cond, msg){
  if (!cond){ console.error('✗ ' + msg); process.exit(1); }
  console.log('✓ ' + msg);
}

(async () => {
  const browser = await chromium.launch({
    args: ['--no-sandbox'], executablePath: fs.existsSync(EXE) ? EXE : undefined
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 2000 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  // 静态服务没有 favicon，浏览器会自动要 /favicon.ico —— 那条
  // "Failed to load resource: 404" 是环境噪音，不是页面的 JS 错误。
  // 混进来会让人习惯性忽略这一行，真出 JS 错误时反而看不见。
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  await page.goto(URL, { waitUntil: 'load' });

  // 动态 import store，清空现有块，加一个 writebox 选择题块
  const built = await page.evaluate(async () => {
    const store = (await import('/assets/js/core/store.js')).store;
    const registry = (await import('/assets/js/core/registry.js')).registry;
    const mod = registry.get('singleChoice');
    // 清空
    store.blocks = [];
    const cfg = mod.defaults();
    cfg.title = '一、手写选择题（请在方框内写 A/B/C/D）';
    cfg.count = 6; cfg.options = 4; cfg.mode = 'writebox'; cfg.hwGap = 5;
    store.addBlock('singleChoice', cfg);
    return { blocks: store.blocks.length, mode: store.blocks[0].config.mode };
  });
  console.log('构造块:', built);
  assert(built.mode === 'writebox', '选择题块已切到 writebox 样式');

  // 触发渲染
  await page.evaluate(() => { window.dispatchEvent(new Event('resize')); });
  await page.waitForTimeout(300);

  // 截图看渲染效果
  const sheet = await page.$('#sheet');
  assert(sheet, '#sheet 存在');
  await sheet.screenshot({ path: OUT_SHEET });
  console.log('渲染截图已存', OUT_SHEET);

  // 导出模板
  const tpl = await page.evaluate(async () => {
    const { exportOmrTemplate } = await import('/assets/js/core/omr.js');
    const t = exportOmrTemplate(document.getElementById('sheet'));
    t._wboxRendered = !!document.querySelector('#sheet .wb .wbox');
    t._qRendered = document.querySelectorAll('#sheet .scq').length;
    return t;
  });
  assert(!errors.length, '无页面 JS 错误（' + (errors.length ? errors[0] : '') + ')');
  assert(tpl._wboxRendered, `writebox 方框已渲染（共 ${tpl._qRendered} 题）`);
  const wq = (tpl.pages || []).flatMap(p => p.questions || []).filter(q => q.write);
  const bq = (tpl.pages || []).flatMap(p => p.questions || []).filter(q => q.options);
  console.log(`  writebox 题: ${wq.length}, bubble 题: ${bq.length}`);
  assert(wq.length === 6, `导出 6 道 write 题（实际 ${wq.length}）`);
  assert(bq.length === 0, '无多余 options 题');
  const w0 = wq[0];
  assert(w0.write && [w0.write.x, w0.write.y, w0.write.w, w0.write.h].every(v => v > 0),
    `write 坐标齐全: ${JSON.stringify(w0.write)}`);

  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(OUT_TEMPLATE, JSON.stringify(tpl, null, 2));
  console.log('模板已写', OUT_TEMPLATE);

  await browser.close();

  // 第 2 步（扫描端 decode_write 链路）在 dev/check_writebox_template.py。
  // **为什么不在这里顺手 execFileSync 调 Python**：本机沙箱里 node 起不了任何子进程
  // （连 cmd.exe 都 EBUSY），那样写在沙箱里会变成一个「看起来跑了、其实没跑」的假绿。
  // 拆成两个脚本、由外面的 shell 串起来，每一步才是真执行、失败也看得见。
  console.log('\n🎉 制卡端 writebox 渲染 → 模板导出 全部通过');
  console.log('   下一步（扫描端 decode_write 链路）：');
  console.log('   scanner/.venv/Scripts/python.exe dev/check_writebox_template.py');
})().catch(e => { console.error(e); process.exit(1); });