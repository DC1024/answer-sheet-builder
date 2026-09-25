// 探针：定位"工作台无题下拉"根因 —— 打印 GB 状态与 gradebook 响应
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');
const EXE = process.env.USERPROFILE + '\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe';
const BASE = process.env.BASE || 'http://192.168.43.18:8081';
const FIX = path.join(__dirname, 'tests', 'fixtures');
const png = n => path.join(FIX, n);
const ROSTER_CSV = '考号,姓名,班级\n2026010234,张伟明,高三(12)班\n2026010235,李思,高三(12)班\n2026010236,王五,高三(12)班\n2026010299,赵六,高三(12)班\n';
const OUT = path.join(__dirname, '_ui_out'); if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });
const RF = path.join(OUT, '名单.csv'); fs.writeFileSync(RF, ROSTER_CSV, 'utf-8');

const waitFor = async (page, fn, ms = 8000, step = 200) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await page.evaluate(fn)) return true; await page.waitForTimeout(step); }
  return false;
};

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1700, height: 1500 } });
  const page = await ctx.newPage();
  await page.goto(BASE + '/login', { waitUntil: 'load' });
  await page.waitForTimeout(300);
  await page.fill('#u', 'e2e_admin');
  await page.fill('#p', 'e2e_pass_2026');
  await page.click('#go');
  const logged = await waitFor(page, () => !!document.getElementById('btnLogout'));
  console.log('登录回到主界面:', logged);

  page.on('dialog', d => d.accept('probe-考试'));
  await page.click('#btnNewExam');
  await page.waitForTimeout(600);

  await page.setInputFiles('#tplFile', png('template.json'));
  await page.click('#btnTpl');
  await waitFor(page, () => (document.getElementById('tplInfo').innerText || '').includes('题'));
  console.log('模板:', await page.evaluate(() => document.getElementById('tplInfo').innerText.trim()));

  await page.setInputFiles('#bFiles', [png('s01.png'), png('s02.png'), png('s03.png'), png('s04.png')]);
  await page.setInputFiles('#bRoster', RF);
  await page.waitForTimeout(300);
  await page.click('#btnBatch');
  const done = await waitFor(page, () => /位考生/.test(document.getElementById('batchInfo').innerText || ''), 15000);
  console.log('批量完成:', done, '|', await page.evaluate(() => document.getElementById('batchInfo').innerText.trim()));

  // 保存答案
  const KEY = require(path.join(FIX, 'expected.json'))['students']['s01']['answers'];
  const keyText = Object.keys(KEY).filter(k => KEY[k]).sort((a, b) => +a - +b).map(k => k + KEY[k]).join(' ');
  await page.fill('#key', keyText);
  await page.click('#btnKey');
  await waitFor(page, () => /已保存|已清空/.test(document.getElementById('toast').textContent || ''), 4000);
  console.log('保存答案 toast:', await page.evaluate(() => document.getElementById('toast').textContent.trim()));

  // 拉 gradebook 打印原始响应
  const gb = await page.evaluate(async () => {
    const r = await fetch('/api/gradebook?' + (location.search || ''), { credentials: 'same-origin' });
    const j = await r.json();
    return { hasKey: j.hasKey, qnos: j.qnos, key: j.key, n: (j.students || []).length, first: j.students && j.students[0] ? { sid: j.students[0].sid, auto: j.students[0].auto, grading: j.students[0].grading } : null };
  });
  console.log('gradebook hasKey=', gb.hasKey, 'qnos=', gb.qnos && gb.qnos.length, 'key#=', Object.keys(gb.key || {}).length, 'students=', gb.n);
  console.log('first:', JSON.stringify(gb.first));

  // 调 loadGradebook 再 openGrade 看 GB
  await page.evaluate(() => loadGradebook());
  await page.waitForTimeout(300);
  const gbState = await page.evaluate(() => GB ? { hasKey: GB.hasKey, qnos: GB.qnos, keyN: Object.keys(GB.key || {}).length } : 'GB 未定义');
  console.log('页面 GB 状态:', JSON.stringify(gbState));

  await page.evaluate(() => { const b = document.querySelector('#gbBody button[data-sid]'); b && b.click(); });
  await page.waitForTimeout(300);
  const qsel = await page.evaluate(() => !!document.querySelector('#gbModalBody select[data-q]'));
  const modalTxt = await page.evaluate(() => (document.getElementById('gbModalBody').innerText || '').slice(0, 120));
  console.log('复核面板有题下拉:', qsel, '| 面板文本:', JSON.stringify(modalTxt));

  await page.screenshot({ path: path.join(OUT, 'probe_modal.png') });
  await browser.close();
})();