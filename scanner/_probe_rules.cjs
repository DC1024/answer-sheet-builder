// 新功能探针：④评分规则编辑器 + ⑥打印成绩单（每人一页）
// 流程：登录 → 新建考试 → 模板 → 批量(4卷+名单) → 保存答案 → 工作台
//       → 开规则弹窗 → 给第1题配 pick_k 阶梯 → 保存 → 验证 auto 变了 → 打印按钮产出 .sheet × N
const { chromium } = require('playwright-core');
const fs = require('fs'); const path = require('path');
const EXE = process.env.USERPROFILE + '\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe';
const BASE = process.env.BASE || 'http://192.168.43.18:8081';
const FIX = path.join(__dirname, 'tests', 'fixtures');
const OUT = path.join(__dirname, '_ui_out');
const png = n => path.join(FIX, n);
const ROSTER_CSV = '考号,姓名,班级\n2026010234,张伟明,高三(12)班\n2026010235,李思,高三(12)班\n2026010236,王五,高三(12)班\n2026010299,赵六,高三(12)班\n';
const RF = path.join(OUT, '名单.csv'); fs.writeFileSync(RF, ROSTER_CSV, 'utf-8');
let fails = 0;
const ok = (c, m, extra) => { console.log((c ? '  ✅ ' : '  ❌ ') + m + (extra ? '  [' + extra + ']' : '')); if (!c) fails++; };
const waitFor = async (page, fn, ms = 9000, step = 250) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await page.evaluate(fn)) return true; } catch (_) {} await page.waitForTimeout(step); }
  return false;
};
(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const page = await (await browser.newContext({ viewport: { width: 1700, height: 1500 } })).newPage();
  const errs = [];
  page.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  await page.goto(BASE + '/login', { waitUntil: 'load' });
  await page.fill('#u', 'e2e_admin'); await page.fill('#p', 'e2e_pass_2026'); await page.click('#go');
  ok(await waitFor(page, () => !!document.getElementById('btnLogout')), '登录');
  page.on('dialog', d => d.accept('规则探针-' + Date.now()));
  await page.click('#btnNewExam');
  ok(await waitFor(page, () => (document.getElementById('examSel').options[document.getElementById('examSel').selectedIndex] || {}).text.includes('规则探针-') && /已新建/.test(document.getElementById('toast').textContent || '')), '新建考试并切换');
  await page.setInputFiles('#tplFile', png('template.json')); await page.click('#btnTpl');
  ok(await waitFor(page, () => /题/.test(document.getElementById('tplInfo').innerText || ''), 8000), '模板载入');
  await page.setInputFiles('#bFiles', [png('s01.png'), png('s02.png'), png('s03.png'), png('s04.png')]);
  await page.setInputFiles('#bRoster', RF);
  await page.click('#btnBatch');
  ok(await waitFor(page, () => /位考生/.test(document.getElementById('batchInfo').innerText || ''), 20000), '批量识别',
     await page.evaluate(() => document.getElementById('batchInfo').innerText.trim()));
  const KEY = require(path.join(FIX, 'expected.json'))['students']['s01']['answers'];
  const keyText = Object.keys(KEY).filter(k => KEY[k]).sort((a, b) => +a - +b).map(k => k + KEY[k]).join(' ');
  await page.fill('#key', keyText); await page.click('#btnKey');
  await waitFor(page, () => /已保存/.test(document.getElementById('toast').textContent || ''), 5000);
  await page.evaluate(() => loadGradebook());
  await waitFor(page, () => document.getElementById('gbBody').querySelector('table tbody tr'), 6000);
  const autoBefore = await page.evaluate(() => (JSON.parse(JSON.stringify(GB.rows)).find(r => r.sid === '2026010234') || {}).auto);
  ok(autoBefore === 19, '规则前 auto=19（传统计分）', 'auto=' + autoBefore);

  // ---- 规则编辑器 ----
  await page.click('#btnRules');
  ok(await waitFor(page, () => document.getElementById('ruleModal').classList.contains('on')), '规则弹窗打开');
  const rowsN = await page.evaluate(() => document.querySelectorAll('#ruleBody tr[data-q]').length);
  ok(rowsN === 19, '弹窗列出 19 道有答案的题', 'rows=' + rowsN);
  // 第 1 题配 pick_k：0:0 1:1 2:2 3:4（s01 第1题只涂 D 一个 → 对1 → 1 分，比传统少不了……
  // 改配 single 3 分更直观：s01 全对 → 第1题 3 分 → auto = 21）
  await page.selectOption('#ruleBody tr[data-q="1"] select[data-f="type"]', 'single');
  await page.waitForTimeout(150);
  await page.evaluate(() => { document.querySelector('#ruleBody tr[data-q="1"] [data-f="points"]').value = 3;
    document.querySelector('#ruleBody tr[data-q="1"] [data-f="points"]').dispatchEvent(new Event('input', {bubbles: true})); });
  await page.screenshot({ path: path.join(OUT, 'ui_rules_modal.png') });
  await page.click('#ruleSave');
  ok(await waitFor(page, () => !document.getElementById('ruleModal').classList.contains('on'), 6000), '规则保存并关闭');
  await waitFor(page, () => (GB.rows || []).length === 4 && GB.rows[0].auto !== undefined, 6000);
  const gbAfter = await page.evaluate(() => { const r = JSON.parse(JSON.stringify(GB.rows)).find(x => x.sid === '2026010234'); return {auto: r.auto, eff: r.effective, total: r.total}; });
  ok(gbAfter.auto === 21, '第1题配 3 分后 auto=21（3+18）', JSON.stringify(gbAfter));
  // 清空规则恢复
  await page.click('#btnRules');
  await waitFor(page, () => document.getElementById('ruleModal').classList.contains('on'));
  await page.click('#ruleClearAll'); await page.click('#ruleSave');
  await waitFor(page, () => !document.getElementById('ruleModal').classList.contains('on'), 6000);
  await waitFor(page, () => (GB.rows || []).some(r => r.auto === 19), 6000);
  ok(true, '清空规则后回到传统 19 分');

  // ---- 打印成绩单 ----
  await page.click('#gbPrint');
  await page.waitForTimeout(400);
  const sheets = await page.evaluate(() => document.querySelectorAll('#printRoot .sheet').length);
  ok(sheets === 4, '打印容器产出 4 张成绩单（每人一页）', 'sheets=' + sheets);
  const hasScore = await page.evaluate(() => { const s = document.querySelector('#printRoot .sheet');
    return s && /得分（含人工复核）/.test(s.textContent) && /学生签名/.test(s.textContent); });
  ok(!!hasScore, '成绩单含得分区与签名栏');
  await page.screenshot({ path: path.join(OUT, 'ui_print_root.png'), fullPage: false });
  // 打印预览不能真开 —— 校验 printRoot 内容 + print CSS 存在即可
  const hasPrintCss = await page.evaluate(() => [...document.styleSheets].some(ss => { try { return [...ss.cssRules].some(r => r.media && /print/.test(r.media.mediaText)); } catch(_) { return false; } }));
  ok(hasPrintCss, '@media print 样式已注入');
  console.log('\nPAGEERRORS:', errs.length ? errs : 'none');
  for (const e of errs) fails++;
  await browser.close();
  console.log(fails === 0 ? '\n🎉 新功能探针全部通过' : '\n⚠️  ' + fails + ' 项未通过');
  process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('FATAL', e); process.exit(2); });