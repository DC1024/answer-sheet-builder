// 制卡端「⚙ 设置 / 检查更新」的前端验证。
//
//   node dev/verify_settings.cjs
//
// 为什么要跑真浏览器：这段逻辑有一半是「浏览器给不给面子」——
//   * app.html 的脚本是 ES Module，只有走 http 才加载得起来（file:// 直接白屏）；
//   * 更新检查是浏览器直接跨域打 GitHub API，会不会被 CORS 拦只有真跑才知道；
//   * 「设置弹窗不能印到卷子上」这条只有换成 print 媒体才能验。
// 所以这里用无头 Chromium 打开真实 app.html，把 GitHub 请求**拦截**成假的
// （离线可跑、结果确定），然后逐条断言。
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

const ROOT = path.resolve(__dirname, '..');
const EXE = path.join(process.env.LOCALAPPDATA || '',
  'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe');

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' };

const FAILS = [];
function ok(cond, msg){
  console.log((cond ? '  ✓ ' : '  ✗ ') + msg);
  if (!cond) FAILS.push(msg);
}
function eq(got, want, msg){
  ok(got === want, `${msg}（期望 ${JSON.stringify(want)}，实测 ${JSON.stringify(got)}）`);
}

/* ---------- 一个只读静态服务器：ES Module 必须有 http 才加载得动 ---------- */
function serve(){
  return new Promise(resolve => {
    const srv = http.createServer((req, res) => {
      let u = decodeURIComponent((req.url || '/').split('?')[0]);
      if (u === '/' || u === '') u = '/app.html';
      const p = path.resolve(ROOT, u.replace(/^[/\\]+/, ''));
      if (!p.startsWith(ROOT)){ res.writeHead(403); return res.end('forbidden'); }
      fs.readFile(p, (err, data) => {
        if (err){ res.writeHead(404); return res.end('404'); }
        res.writeHead(200, { 'Content-Type': MIME[path.extname(p).toLowerCase()] || 'application/octet-stream' });
        res.end(data);
      });
    });
    srv.listen(0, '127.0.0.1', () => resolve({ srv, port: srv.address().port }));
  });
}

const RELEASE = {
  tag_name: 'v9.9.9',
  name: 'v9.9.9 · 假发行版（测试用）',
  body: '### 测试\n- 这是一条假的发行说明',
  html_url: 'https://github.com/DC1024/answer-sheet-builder/releases/tag/v9.9.9',
  published_at: '2026-10-01T12:00:00Z',
};

(async () => {
  const { srv, port } = await serve();
  const base = `http://127.0.0.1:${port}`;
  const browser = await chromium.launch({ executablePath: EXE, headless: true });
  const ctx = await browser.newContext();

  // 把 GitHub API 拦成假的：可选「有新版本 / 已是最新 / 断网」三种剧本
  let script = 'newer';
  await ctx.route('https://api.github.com/**', route => {
    if (script === 'fail') return route.abort('connectionfailed');
    const tag = script === 'newer' ? RELEASE.tag_name : 'v1.0.3';
    route.fulfill({
      status: 200,
      contentType: 'application/json; charset=utf-8',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(Object.assign({}, RELEASE, { tag_name: tag })),
    });
  });

  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));

  await page.goto(base + '/app.html');
  await page.waitForSelector('#sheet', { timeout: 15000 });

  console.log('\n【1】装载');
  eq(errors.length, 0, '控制台没有报错');
  ok(await page.isVisible('#btn-settings'), '工具栏出现「⚙ 设置」按钮');
  ok(await page.isHidden('#setModal'), '设置弹窗默认是收起的');

  console.log('\n【2】打开设置');
  await page.click('#btn-settings');
  ok(await page.isVisible('#setModal'), '点按钮 → 弹窗打开');
  eq((await page.textContent('#setVer')).trim(), 'v1.0.3', '显示当前版本号');
  ok(await page.isChecked('#setAutoUpd'), '「自动检查更新」默认开启');

  console.log('\n【3】自动检查更新（后台）');
  // bindSettings 里的 maybeAutoCheck 是异步的，等页头按钮亮出角标
  await page.waitForFunction(
    () => (document.getElementById('btn-settings').textContent || '').includes('●'),
    null, { timeout: 8000 }
  ).catch(() => {});
  ok((await page.textContent('#btn-settings')).includes('●'),
     '自动查到新版本 → 设置按钮上出角标（不打断用户）');

  console.log('\n【4】手动检查更新：有新版本');
  await page.click('#setCheck');
  await page.waitForSelector('#setResult:not([hidden])', { timeout: 8000 });
  const hit = await page.textContent('#setResult');
  ok(hit.includes('v9.9.9'), '结果区报出新版本号', );
  ok(hit.includes('假的发行说明'), '带上发行说明正文');
  eq(await page.getAttribute('#setResult a', 'href'), RELEASE.html_url, '给出可点的发行版地址');
  eq(await page.getAttribute('#setResult', 'class'), 'hit', '结果区用「有新版本」的高亮样式');

  console.log('\n【5】手动检查更新：已是最新');
  script = 'latest';
  await page.click('#setCheck');
  await page.waitForFunction(
    () => (document.getElementById('setInfo').textContent || '').includes('已是最新'),
    null, { timeout: 8000 });
  ok((await page.textContent('#setInfo')).includes('已是最新'), '没有新版本时明说「已是最新」');
  ok(await page.isHidden('#setResult'), '没有新版本时不显示结果框');

  console.log('\n【6】手动检查更新：查不到（断网 / 内网）');
  script = 'fail';
  await page.click('#setCheck');
  await page.waitForSelector('#setResult:not([hidden])', { timeout: 8000 });
  const miss = await page.textContent('#setResult');
  ok(miss.includes('暂时查不到'), '查不到时不报红，只说「暂时查不到」');
  ok(miss.includes('发行版页面'), '查不到时给出手动入口');
  eq(await page.getAttribute('#setResult', 'class'), '', '查不到不用「有新版本」的高亮样式');

  console.log('\n【7】开关持久化（localStorage）');
  await page.uncheck('#setAutoUpd');
  await page.waitForTimeout(200);
  eq(await page.evaluate(() => JSON.parse(localStorage.getItem('asb.settings')).autoCheckUpdate),
     false, '关掉后写进 localStorage');
  await page.check('#setAutoUpd');
  await page.waitForTimeout(200);
  eq(await page.evaluate(() => JSON.parse(localStorage.getItem('asb.settings')).autoCheckUpdate),
     true, '再打开也写进去了');
  // 关掉之后刷新，不应该再去查（route 计数）
  await page.uncheck('#setAutoUpd');
  await page.waitForTimeout(200);

  console.log('\n【8】关闭方式 + 打印不输出');
  await page.keyboard.press('Escape');
  ok(await page.isHidden('#setModal'), 'Esc 能关掉弹窗');
  await page.click('#btn-settings');
  await page.emulateMedia({ media: 'print' });
  ok(await page.isHidden('#setModal'), '**打印 / 导出 PDF 时设置弹窗不出现**（不会印到卷子上）');
  await page.emulateMedia({ media: 'screen' });
  await page.click('#setClose');
  ok(await page.isHidden('#setModal'), '「关闭」按钮能关掉弹窗');

  console.log('\n【9】刷新后开关仍然生效');
  await page.reload();
  await page.waitForSelector('#sheet', { timeout: 15000 });
  await page.click('#btn-settings');
  ok(!(await page.isChecked('#setAutoUpd')), '刷新后读回「关掉自动检查」的状态');

  await browser.close();
  srv.close();

  console.log('\n' + '='.repeat(56));
  if (FAILS.length){
    console.log(`⚠️  ${FAILS.length} 项未通过：`);
    FAILS.forEach(f => console.log('   - ' + f));
    process.exit(1);
  }
  console.log('🎉 制卡端设置 / 检查更新前端验证全部通过');
})().catch(e => { console.error('✗ 脚本异常：', e); process.exit(1); });
