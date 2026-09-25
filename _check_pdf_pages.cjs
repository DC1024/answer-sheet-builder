// 验证：答题卡只有正面有内容时，导出 PDF 只有 1 页（背面空白不导出）
// 用法：node _check_pdf_pages.cjs   （需先起 http 服务指向仓库根，端口 8099）
const { chromium } = require('playwright-core');
const path = require('path');
const EXE = process.env.USERPROFILE + '\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe';
const BASE = process.env.BASE || 'http://127.0.0.1:8099';
let fails = 0;
const ok = (c, m, extra) => { console.log((c ? '  ✅ ' : '  ❌ ') + m + (extra ? '  [' + extra + ']' : '')); if (!c) fails++; };

const SEED1 = [   // 一面都填不满的少量内容（A4 竖版单栏）
  {id: 'b1', type: 'info', config: {title: '考生信息', examGrid: true, examDigits: 10}},
  {id: 'b2', type: 'singleChoice', config: {title: '一、单选题', options: 4, startNo: 1, count: 8}},
];
const SEED2 = [   // 足量内容：必然溢出到第二面
  {id: 'b1', type: 'info', config: {title: '考生信息', examGrid: true, examDigits: 10}},
  {id: 'b2', type: 'singleChoice', config: {title: '一、单选题', options: 4, startNo: 1, count: 60}},
];

const pdfPageCount = buf => (buf.toString('latin1').match(/\/Type\s*\/Page[^s]/g) || []).length;

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const page = await (await browser.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));

  for (const [name, seed, wantPages] of [['少量内容(1面)', SEED1, 1], ['大量内容(2面)', SEED2, 2]]){
    await page.goto(BASE + '/app.html', { waitUntil: 'load' });
    await page.evaluate(seedBlocks => {
      localStorage.removeItem('answer-sheet-builder.v1');
      return import('./assets/js/core/store.js').then(async ({store}) => {
        store.paper = { size: 'A4', orientation: 'portrait', marks: 'square', markSize: 4 };
        store.blocks = seedBlocks;
        store.emit();
      });
    }, seed);
    await page.waitForTimeout(500);
    const screenPages = await page.evaluate(() => document.querySelectorAll('#sheet .page').length);
    ok(screenPages === wantPages, `${name}：屏幕预览 ${wantPages} 面`, 'pages=' + screenPages);
    await page.emulateMedia({ media: 'print' });
    const buf = await page.pdf({ printBackground: true, preferCSSPageSize: true, path: path.join(__dirname, `_ui_out/_pdf_${wantPages}p.pdf`) });
    const n = pdfPageCount(buf);
    ok(n === wantPages, `${name}：导出 PDF 共 ${wantPages} 页（无空白尾页）`, 'pdf pages=' + n);
    await page.emulateMedia({ media: null });
  }
  // 纸张尺寸 @page 同步
  await page.goto(BASE + '/app.html', { waitUntil: 'load' });
  const at = await page.evaluate(async () => {
    await import('./assets/js/core/store.js').then(({store}) => {
      store.paper = { size: 'A3', orientation: 'landscape', marks: 'square', markSize: 4 };
      store.blocks = [{id: 'b1', type: 'info', config: {title: 'x'}}];
      store.emit();
    });
    return document.getElementById('printPageSize') ? document.getElementById('printPageSize').textContent : '';
  });
  ok(/size:\s*420mm\s*297mm/.test(at), 'A3 横版时 @page 同步为 420mm×297mm', at.trim());
  console.log('\nPAGEERRORS:', errs.length ? errs : 'none');
  for (const e of errs) fails++;
  await browser.close();
  console.log(fails === 0 ? '\n🎉 PDF 页数验证全部通过' : '\n⚠️  ' + fails + ' 项未通过');
  process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('FATAL', e); process.exit(2); });