// 重新生成 scanner/tests/fixtures/ 里的测试素材。
//
// 做法：用无头 Chromium 打开真实的制卡端 app.html，直接调 exportOmrTemplate()
// 拿到阅卷模板，再用 CSS 把指定选项「涂」成深色/浅灰，逐份截图导出 PNG。
// 这样素材永远与制卡端的实际渲染一致 —— 不会出现「测试过了但真机对不上」。
//
// 依赖（仅开发用，不进任何镜像）：
//   npm i playwright-core     # 或复用已有安装，用 NODE_PATH 指过去
//   一个 Chromium 可执行文件
// 用法：
//   # 先在仓库根目录起一个静态服务
//   python -m http.server 8080
//   # 另开一个终端
//   node dev/gen_omr_fixtures.cjs
//   BASE=http://127.0.0.1:8080 CHROME=/path/to/chrome node dev/gen_omr_fixtures.cjs
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const URL = (process.env.BASE || 'http://127.0.0.1:8080') + '/app.html';
const OUT = path.join(__dirname, '..', 'scanner', 'tests', 'fixtures');
const EXE = process.env.CHROME || path.join(
  process.env.LOCALAPPDATA || '', 'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe');

const N_Q = 20;          // 20 道选择题
const N_OPT = 4;         // A-D
const STUDENTS = 6;

// 每个学生的答案（含 1 道空白、1 道浅涂，用来验证存疑标记）
function answersFor(s){
  const out = {};
  for (let q = 1; q <= N_Q; q++){
    const r = (q * 7 + s * 3) % N_OPT;
    out[q] = 'ABCD'[r];
  }
  out[3] = null;                    // 未填
  out[8] = out[8] + ':light';       // 浅涂
  return out;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const launch = { args: ['--no-sandbox'] };
  if (fs.existsSync(EXE)) launch.executablePath = EXE;
  const browser = await chromium.launch(launch);

  // deviceScaleFactor 4 → 1mm ≈ 15.1px ≈ 383dpi，比真实扫描仪更高，足以验证算法
  const page = await browser.newPage({ viewport: { width: 1400, height: 1600 }, deviceScaleFactor: 4 });
  page.on('pageerror', e => console.log('PAGEERROR:', e.message));
  await page.goto(URL, { waitUntil: 'load' });
  await page.waitForTimeout(400);

  const tpl = await page.evaluate(async ({ N_Q, N_OPT }) => {
    const { store } = await import('./assets/js/core/store.js');
    const { registry } = await import('./assets/js/core/registry.js');
    const { renderPreview } = await import('./assets/js/core/preview.js');
    const { exportOmrTemplate } = await import('./assets/js/core/omr.js');
    store.paper = { size: 'A4', orientation: 'portrait', marks: 'square', markSize: 4 };
    store.blocks = [{ id: 'c1', type: 'singleChoice', config: Object.assign(registry.get('singleChoice').defaults(),
      { title: '一、选择题', count: N_Q, cols: 5, options: N_OPT, mode: 'bubble', startNo: 1 }) }];
    const sheet = document.getElementById('sheet');
    renderPreview(sheet);
    return exportOmrTemplate(sheet);
  }, { N_Q, N_OPT });
  fs.writeFileSync(path.join(OUT, 'template.json'), JSON.stringify(tpl, null, 2));
  console.log('template.json：', tpl.questionCount, '题 /', tpl.pages.length, '面');

  const expected = {};
  for (let s = 0; s < STUDENTS; s++){
    const ans = answersFor(s);
    const name = `s${String(s + 1).padStart(2, '0')}`;
    expected[name] = {};
    for (const q of Object.keys(ans)){
      const v = ans[q];
      expected[name][q] = v === null ? null : String(v).split(':')[0];
    }
    await page.evaluate(async (ans) => {
      const sheet = document.getElementById('sheet');
      // 先清空上一次的填涂。boxShadow 必须一起清 —— 只清 background 会留下
      // 上一份卷子的阴影，表现为「没涂的圈检测出 0.85 的墨迹」。
      sheet.querySelectorAll('.bub .bracket').forEach(b => {
        b.style.background = ''; b.style.borderColor = ''; b.style.color = '';
        b.style.borderRadius = ''; b.style.boxShadow = '';
      });
      for (const q of Object.keys(ans)){
        const v = ans[q];
        if (v === null) continue;
        const [letter, kind] = String(v).split(':');
        const b = sheet.querySelector(`.scq[data-q="${q}"] .bub[data-opt="${letter}"] .bracket`);
        if (!b) continue;
        const ink = kind === 'light' ? '#9c9c9c' : '#2c2c2c';
        b.style.background = ink;
        b.style.borderColor = ink;
        b.style.color = ink;
        b.style.borderRadius = '50%';
        b.style.boxShadow = `inset 0 0 0 12px ${ink}`;
      }
    }, ans);
    const el = await page.$('#sheet .page');
    await el.screenshot({ path: path.join(OUT, name + '.png') });
    console.log('  ->', name + '.png');
  }
  fs.writeFileSync(path.join(OUT, 'expected.json'), JSON.stringify(expected, null, 2));
  await browser.close();
  console.log('素材生成完毕 ->', OUT);
})();
