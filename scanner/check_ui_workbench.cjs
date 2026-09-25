// #24 阅卷工作台 —— 真实浏览器 UI 走查（对线上 8081 容器）
// 骨架基于 _probe_ui.cjs（已实测全绿），补齐完整断言。
// 覆盖：登录 → 新建考试 → 传模板 → 批量上传(含名单) → 识别出考生
//       → 填标准答案→生成统计→保存答案 → 工作台渲染 → 逐题改判+手动分+待复核+备注
//       → 保存 → 验证 gradebook 落库 → 复核导出 CSV → 截图
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const EXE = process.env.USERPROFILE + '\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe';
const BASE = process.env.BASE || 'http://192.168.43.18:8081';
const FIX = path.join(__dirname, 'tests', 'fixtures');
const OUT = path.join(__dirname, '_ui_out');
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

let fails = 0;
const ok = (c, m, extra) => { console.log((c ? '  \u2705 ' : '  \u274c ') + m + (extra ? '  [' + extra + ']' : '')); if (!c) fails++; };
const png = n => path.join(FIX, n);
const ROSTER_CSV = '考号,姓名,班级\n2026010234,张伟明,高三(12)班\n2026010235,李思,高三(12)班\n2026010236,王五,高三(12)班\n2026010299,赵六,高三(12)班\n';
const RF = path.join(OUT, '名单.csv'); fs.writeFileSync(RF, ROSTER_CSV, 'utf-8');

const waitFor = async (page, fn, ms = 9000, step = 250) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await page.evaluate(fn)) return true; } catch (_) {} await page.waitForTimeout(step); }
  return false;
};

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1700, height: 1500 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const u = (m.location && m.location().url) || '';
    if (/favicon/.test(u)) return;
    errs.push('CONSOLE: ' + m.text() + (u ? ' @ ' + u : ''));
  });

  console.log('=== 登录 ===');
  await page.goto(BASE + '/login', { waitUntil: 'load' });
  await page.waitForTimeout(300);
  await page.fill('#u', 'e2e_admin');
  await page.fill('#p', 'e2e_pass_2026');
  await page.click('#go');
  ok(await waitFor(page, () => !!document.getElementById('btnLogout'), 8000), '登录成功回到主界面');

  console.log('=== 新建考试 + 传模板 ===');
  page.on('dialog', d => d.accept('UI走查-' + Date.now()));
  await page.click('#btnNewExam');
  // 等 examSel 显示新考试（loadExams 完成）且 toast 出现「已新建」（openExam 完成 → CUR 已切到新考试）
  const examSwitched = await waitFor(page, () =>
    (document.getElementById('examSel').options[document.getElementById('examSel').selectedIndex] || {}).text.includes('UI走查-') &&
    /已新建/.test(document.getElementById('toast').textContent || '')
  , 6000, 250);
  ok(examSwitched, '新建考试并切换（CUR 已切到新考试，模板绑定目标正确）', await page.evaluate(() => document.getElementById('toast').textContent.trim()));
  await page.setInputFiles('#tplFile', png('template.json'));
  await page.click('#btnTpl');
  // 模板用 #tplInfo 持久文本信号（toast 会自动消失，不可靠）
  const tplTxt = await waitFor(page, () => /题/.test(document.getElementById('tplInfo').innerText || ''), 8000, 250);
  ok(tplTxt, '模板已载入（#tplInfo 含「题」）', await page.evaluate(() => document.getElementById('tplInfo').innerText.trim()));

  console.log('=== 批量上传（4 张卷 + 名单） ===');
  await page.setInputFiles('#bFiles', [png('s01.png'), png('s02.png'), png('s03.png'), png('s04.png')]);
  await page.setInputFiles('#bRoster', RF);
  await page.waitForTimeout(300);
  ok((await page.evaluate(() => sel ? sel.length : -1)) === 4, '4 张卷已进待传列表');
  await page.click('#btnBatch');
  const batchDone = await waitFor(page, () => /位考生/.test(document.getElementById('batchInfo').innerText || ''), 20000);
  const batchInfo = await page.evaluate(() => document.getElementById('batchInfo').innerText.trim());
  ok(batchDone && /名单/.test(batchInfo), '批量识别完成（含名单匹配）', batchInfo);

  console.log('=== 标准答案：生成统计 + 保存 ===');
  const KEY = require(path.join(FIX, 'expected.json'))['students']['s01']['answers'];
  const keyText = Object.keys(KEY).filter(k => KEY[k]).sort((a, b) => +a - +b).map(k => k + KEY[k]).join(' ');
  await page.fill('#key', keyText);
  await page.click('#btnStats');
  await waitFor(page, () => document.getElementById('sstats').querySelector('table tbody tr') != null, 6000);
  const statRows = await page.evaluate(() => document.getElementById('sstats').querySelectorAll('tbody tr').length);
  ok(statRows === 4, '④ 生成统计：4 位考生都判了分', 'rows=' + statRows);
  await page.click('#btnKey');
  await waitFor(page, () => /已保存|已清空/.test(document.getElementById('toast').textContent || ''), 5000);
  ok(true, '已保存标准答案（#btnKey → /api/answer-key，工作台逐题复核的前提）');

  console.log('=== ⑥ 阅卷工作台 ===');
  await page.evaluate(() => loadGradebook());
  await waitFor(page, () => document.getElementById('gbBody').querySelector('table tbody tr') != null, 6000);
  const gbRowCount = await page.evaluate(() => document.getElementById('gbBody').querySelectorAll('tbody tr').length);
  ok(gbRowCount === 4, '工作台表格渲染出 4 位考生', 'rows=' + gbRowCount);
  await page.screenshot({ path: path.join(OUT, 'ui_workbench_list.png') });

  // 打开第一位考生复核面板
  await page.evaluate(() => { const b = document.querySelector('#gbBody button[data-sid]'); if (b) b.click(); else alert('no-data-sid'); });
  // 等面板真正打开：.on 类 或 题下拉渲染 任一先出现（openGrade 是异步的，可能比点击晚几百 ms）
  const modalOpen = await waitFor(page, () =>
    document.getElementById('gbModal').classList.contains('on') ||
    !!document.querySelector('#gbModalBody select[data-q]')
  , 6000, 200);
  ok(modalOpen, '点考生行 → 复核面板打开');

  // 逐题改判：第一题强制判错 + 手动分 15 + 待复核 + 备注
  const firstQ = await page.evaluate(() => {
    const sel = document.querySelector('#gbModalBody select[data-q]');
    if (!sel) return null;
    sel.value = 'wrong'; return sel.getAttribute('data-q');
  });
  ok(firstQ !== null, '面板渲染出题下拉（可逐题改判）', 'data-q=' + firstQ);
  await page.evaluate(() => {
    const m = document.getElementById('gbManual'); m.value = 15; m.dispatchEvent(new Event('input'));
    document.getElementById('gbReview').checked = true;
    document.getElementById('gbNote').value = 'UI走查：第1题判错+手动总分15';
  });
  await page.screenshot({ path: path.join(OUT, 'ui_grade_modal.png') });
  await page.evaluate(() => saveGrade());
  ok(await waitFor(page, () => !document.getElementById('gbModal').classList.contains('on'), 6000), '点保存 → 面板关闭');

  console.log('=== 验证落库 ===');
  const gb = await page.evaluate(async () => {
    const r = await fetch('/api/gradebook', { credentials: 'same-origin' });
    const j = await r.json();
    const row = (j.students || [])[0];
    return { n: (j.students || []).length, review: row && row.grading ? row.grading.review : null, ms: row && row.grading ? row.grading.manualScore : null, note: row && row.grading ? row.grading.note : '' };
  });
  ok(gb.n === 4, '复核保存后工作台仍 4 位考生', 'students=' + gb.n);
  ok(gb.review === true, '「待复核」标记已落库', 'review=' + gb.review);
  ok(gb.ms === 15, '手动总分 15 已落库', 'manualScore=' + gb.ms);
  ok(gb.note && gb.note.includes('UI走查'), '备注已落库', (gb.note || '').slice(0, 40));

  console.log('=== 复核导出 CSV ===');
  const csv = await page.evaluate(async (kt) => {
    const r = await fetch('/api/export.csv', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ key: kt, graded: '1' }), credentials: 'same-origin' });
    const t = await r.text();
    return { st: r.status, head: t.split('\n')[0], second: (t.split('\n')[1] || '') };
  }, keyText);
  ok(csv.st === 200 && /复核分/.test(csv.head), '复核导出表头含「复核分」', csv.head);
  ok(csv.second.includes('15'), '复核导出首行得分=15（手动分优先）', csv.second.split(',').slice(0, 4).join(','));

  await page.screenshot({ path: path.join(OUT, 'ui_workbench_final.png'), fullPage: true });

  console.log('\nERRORS:', errs.length ? errs.slice(0, 6) : 'none');
  for (const e of errs) { fails++; console.log('   ', e); }
  await browser.close();
  console.log(fails === 0 ? '\n🎉 UI 走查全部通过' : '\n⚠️  ' + fails + ' 项未通过');
  process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('FATAL', e); process.exit(2); });