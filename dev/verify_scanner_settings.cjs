// 扫描端「⑧ 设置 / 检查更新」的前端验证（无头 Chromium + 真实 Flask 服务）。
//
//   node dev/verify_scanner_settings.cjs
//
// 和制卡端不同，这里的更新检查是**服务端**发起的，所以不能用浏览器的路由
// 拦截来造假 —— 改为把扫描端的 `ASB_UPDATE_API` 指到一个本脚本起的假 GitHub
// API 上。这样整条链路（前端 → /api/update → app/update.py → HTTP → 解析 →
// 落盘 settings.json）都是真的，只有那个「外面的世界」是假的。
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright-core');

const ROOT = path.resolve(__dirname, '..');
const SCANNER = path.join(ROOT, 'scanner');
const PY = path.join(SCANNER, '.venv', 'Scripts', 'python.exe');
const EXE = path.join(process.env.LOCALAPPDATA || '',
  'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe');

const USER = 'admin';
const PW = 'admintest1234';
const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'asb-ui-settings-'));

const FAILS = [];
const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) FAILS.push(m); };
const eq = (g, w, m) => ok(g === w, `${m}（期望 ${JSON.stringify(w)}，实测 ${JSON.stringify(g)}）`);

const RELEASE = {
  tag_name: 'v9.9.9',
  name: 'v9.9.9 · 假发行版（测试用）',
  body: '### 测试\n- 这是一条假的发行说明',
  html_url: 'https://github.com/DC1024/answer-sheet-builder/releases/tag/v9.9.9',
  published_at: '2026-10-01T12:00:00Z',
};

function listen(handler){
  return new Promise(res => {
    const srv = http.createServer(handler);
    srv.listen(0, '127.0.0.1', () => res({ srv, port: srv.address().port }));
  });
}

async function waitHttp(url, timeoutMs = 30000){
  const until = Date.now() + timeoutMs;
  while (Date.now() < until){
    try {
      const r = await fetch(url);
      if (r.ok) return true;
    } catch (e){ /* 还没起来 */ }
    await new Promise(r => setTimeout(r, 300));
  }
  throw new Error('等 ' + url + ' 超时');
}

(async () => {
  // ---------- 假 GitHub API ----------
  let mode = 'newer';
  const api = await listen((req, res) => {
    const tag = mode === 'newer' ? RELEASE.tag_name : 'v1.0.3';
    const body = JSON.stringify(Object.assign({}, RELEASE, { tag_name: tag }));
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8',
                         'Access-Control-Allow-Origin': '*' });
    res.end(body);
  });

  // ---------- 真扫描端（更新地址指向假 API） ----------
  const boot = `
import os
from waitress import serve
from app.server import create_app
serve(create_app(), host='127.0.0.1', port=int(os.environ['PORT']), threads=4, ident='asb-scanner')
`;
  const web = await listen(() => {});        // 先占个端口拿到号，再让 python 用它
  const webPort = web.port;
  web.srv.close();

  const child = spawn(PY, ['-c', boot], {
    cwd: SCANNER,
    env: Object.assign({}, process.env, {
      PORT: String(webPort),
      ASB_DATA: DATA,
      ASB_DB: path.join(DATA, 'asb.db'),
      ASB_UPDATE_API: `http://127.0.0.1:${api.port}/latest`,
    }),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let childLog = '';
  child.stdout.on('data', d => { childLog += d.toString(); });
  child.stderr.on('data', d => { childLog += d.toString(); });

  const base = `http://127.0.0.1:${webPort}`;

  try {
    await waitHttp(base + '/api/health');

    const browser = await chromium.launch({ executablePath: EXE, headless: true });
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));

    // 建管理员 + 登录（用 context 的 request：cookie 与页面共享）
    const r1 = await ctx.request.post(base + '/api/setup', { data: { username: USER, password: PW } });
    ok(r1.ok(), '初始化管理员账号成功');
    const r2 = await ctx.request.post(base + '/api/login', { data: { username: USER, password: PW } });
    ok(r2.ok(), '登录成功');

    await page.goto(base + '/');
    await page.waitForSelector('#setCard', { timeout: 15000 });

    console.log('\n【1】设置卡片');
    eq(errors.length, 0, '控制台没有报错');
    ok(await page.isVisible('#setCard'), '页面上出现「⑧ 设置」卡片');
    // 版本号 / 开关是 loadSettings() 异步填的（boot 里刻意不 await，不拖慢首屏），
    // 所以这里必须等它落地再断言 —— 元素在 DOM 里 ≠ 已经填好值。
    await page.waitForFunction(
      () => /^v\d/.test(document.getElementById('setVer').textContent || ''),
      null, { timeout: 10000 });
    eq((await page.textContent('#setVer')).trim(), 'v1.0.3', '显示当前版本号');
    ok(await page.isChecked('#setAutoUpd'), '「自动检查更新」默认开启');

    console.log('\n【2】自动检查（打开界面时，后台）');
    // loadSettings 不 await，轮询等它落到终态。
    // 注意不能把「#setUpdInfo 有字」当终态 —— checkUpdate 一进来就写「正在查询…」，
    // 那样第一帧就返回了，断言结果框时请求还在飞（这就是本用例最初误报的原因）。
    await page.waitForFunction(
      () => {
        const b = document.getElementById('setUpdBox');
        if (!b.hidden) return true;                        // 结果框已展开
        const t = document.getElementById('setUpdInfo').textContent || '';
        return t.includes('已是最新') || t.includes('失败'); // 「正在查询…」不算终态
      },
      null, { timeout: 10000 });
    ok(!(await page.isHidden('#setUpdBox')), '自动查到了新版本 → 结果区自动展开');
    ok((await page.textContent('#setUpdBox')).includes('v9.9.9'), '结果区报出新版本号 v9.9.9');

    console.log('\n【3】手动检查更新：已是最新');
    mode = 'latest';
    await page.click('#btnUpd');
    await page.waitForFunction(
      () => (document.getElementById('setUpdInfo').textContent || '').includes('已是最新'),
      null, { timeout: 10000 });
    ok((await page.textContent('#setUpdInfo')).includes('已是最新'), 'force 检查后明说「已是最新」');
    ok(await page.isHidden('#setUpdBox'), '没有新版本时不显示结果框');

    console.log('\n【4】手动检查更新：有新版本（不缓存旧的「已是最新」）');
    mode = 'newer';
    await page.click('#btnUpd');
    await page.waitForSelector('#setUpdBox:not([hidden])', { timeout: 10000 });
    const box = await page.textContent('#setUpdBox');
    ok(box.includes('v9.9.9'), '切换剧本后立刻报出新版本');
    ok(box.includes('假的发行说明'), '带上发行说明正文');
    eq(await page.getAttribute('#setUpdBox a', 'href'), RELEASE.html_url, '给出可点的发行版地址');

    console.log('\n【5】开关落盘（服务端 settings.json）');
    const settingsFile = path.join(DATA, 'settings.json');
    await page.uncheck('#setAutoUpd');
    await page.waitForTimeout(600);
    eq(JSON.parse(fs.readFileSync(settingsFile, 'utf8')).auto_check_update, false,
       '关掉后写进服务端 settings.json');
    await page.check('#setAutoUpd');
    await page.waitForTimeout(600);
    eq(JSON.parse(fs.readFileSync(settingsFile, 'utf8')).auto_check_update, true,
       '再打开也写进去了');

    console.log('\n【6】关掉自动检查后刷新页面 → 不再自动查');
    await page.uncheck('#setAutoUpd');
    await page.waitForTimeout(600);
    let hits = 0;
    api.srv.on('request', () => { hits += 1; });
    await page.reload();
    await page.waitForSelector('#setCard', { timeout: 15000 });
    await page.waitForTimeout(1500);
    eq(hits, 0, '刷新页面后没有再去查 GitHub（开关真的起作用）');
    ok(!(await page.isChecked('#setAutoUpd')), '刷新后读回「关掉」的状态');

    console.log('\n【7】重新打开开关 → 立刻展示结果（走缓存，不再打一次 GitHub）');
    await page.check('#setAutoUpd');
    await page.waitForSelector('#setUpdBox:not([hidden])', { timeout: 10000 });
    ok(!(await page.isHidden('#setUpdBox')), '重新打开开关后马上把结果摆出来');
    eq(hits, 0, '6 小时内的成功结果走缓存，没有重复打 GitHub');

    console.log('\n【8】只读账号：能看不能改');
    const mk = await ctx.request.post(base + '/api/users',
      { data: { username: 'vv', password: 'viewpass1234', role: 'viewer' } });
    ok(mk.ok(), '建只读账号成功');
    const ctx2 = await browser.newContext();
    const lg = await ctx2.request.post(base + '/api/login',
      { data: { username: 'vv', password: 'viewpass1234' } });
    ok(lg.ok(), '只读账号登录成功');
    const p2 = await ctx2.newPage();
    await p2.goto(base + '/');
    await p2.waitForSelector('#setCard', { timeout: 15000 });
    await p2.waitForFunction(
      () => /^v\d/.test(document.getElementById('setVer').textContent || ''),
      null, { timeout: 10000 });
    const who = (await p2.textContent('#whoami') || '').trim();
    const dis = await p2.getAttribute('#setAutoUpd', 'disabled');
    ok(dis !== null, `只读账号的开关是禁用的（who=${who}）`);
    ok((await p2.textContent('#setVer')).startsWith('v'), '只读账号仍然能看到当前版本');
    ok(await p2.isChecked('#setAutoUpd'), '只读账号读得到开关状态（默认开）');
    // 只读账号点「检查更新」应该还能用（只是查询，不改任何东西）
    await p2.click('#btnUpd');
    await p2.waitForSelector('#setUpdBox:not([hidden])', { timeout: 10000 });
    ok((await p2.textContent('#setUpdBox')).includes('v9.9.9'), '只读账号也能自己点一下「检查更新」并拿到结果');
    ok(errors.length === 0, '整轮下来前端控制台没有报错');

    await browser.close();
  } finally {
    child.kill();
    api.srv.close();
    if (FAILS.length) console.log('\n--- 扫描端日志尾部 ---\n' + childLog.split('\n').slice(-15).join('\n'));
  }

  console.log('\n' + '='.repeat(56));
  if (FAILS.length){
    console.log(`⚠️  ${FAILS.length} 项未通过：`);
    FAILS.forEach(f => console.log('   - ' + f));
    process.exit(1);
  }
  console.log('🎉 扫描端设置 / 检查更新前端验证全部通过');
})().catch(e => { console.error('✗ 脚本异常：', e); process.exit(1); });
