// 端到端验证（设置 → 检查更新 / 自更新面板 UI）：真服务 + 真浏览器点一遍。
//
// 前置：先由 dev/seed_update_ui.py 起服务（默认 http://127.0.0.1:8197）。
//       所有 /api/* 的响应在本脚本里用 playwright 的 route 拦截伪造 —— 因为要
//       **确定性地**演出三种时序（重启中 / 起来了还是旧版本 / 起来了是新版本），
//       靠真进程赛跑是测不稳的。真实服务负责的是「页面能不能正常加载、元素在不在」。
//
// 为什么要有这一层：这块 UI 在 1.4.0 出过真事故 —— 点了「安装并重启」之后
// 窗口没再起来、手动打开版本号也没变。当时后端接口全是 200（绿），坏的全在
// 「界面怎么反映结果」这一段：
//   · 老实现盲等 4 秒就 reload —— 窗口没起来就还是老页面，用户只看到「没反应」
//   · 引导程序崩在服务已经退出之后，没有界面能看到，于是静默失败
//   · 「安装失败」的原因没往界面上送
// 这些都只能靠真浏览器点出来。
//
// 用法：
//   NODE_PATH=<node_modules> node dev/verify_update_ui.cjs
//   环境变量：BASE / CHROME / PORT
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || '8197';
const BASE = process.env.BASE || ('http://127.0.0.1:' + PORT);
const EXE = process.env.CHROME || path.join(process.env.LOCALAPPDATA || '', 'ms-playwright',
  'chromium-1234', 'chrome-win64', 'chrome.exe');
const USER = process.env.ADMIN_USER || 'uiadmin';
const PW = process.env.ADMIN_PW || 'uitest12345';
const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, '.cache', 'shots');

let FAILS = 0, PASS = 0;
function assert(cond, msg, extra){
  if (!cond){ FAILS++; console.error('  x ' + msg + (extra ? '  ' + extra : '')); }
  else { PASS++; console.log('  v ' + msg + (extra ? '  ' + extra : '')); }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const flat = s => String(s || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

async function shot(page, name){
  try {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const p = path.join(SHOT_DIR, name + '.png');
    await page.screenshot({ path: p, fullPage: false });
    console.log('  （截图）' + p);
  } catch (e) { console.log('  （截图失败，忽略）' + e.message); }
}

// —— 假服务端：只拦「更新」相关的接口，其余放行到真服务 ——
// 为什么不能整个页面都 mock：`GET /` 在服务端就被 `AUTH.current()` 挡着，
// 没有真实会话 cookie 会直接 redirect 到 /login（页面根本进不去）。所以先用
// 真账号登录拿到 cookie，再只把 /api/update* /api/settings /api/health 换掉。
const MOCKED = new Set(['/api/settings', '/api/update', '/api/update/progress',
                        '/api/update/install', '/api/update/last-boot', '/api/health']);
function makeBackend(state){
  return async route => {
    const p = new URL(route.request().url()).pathname;
    if (!MOCKED.has(p)) return route.fallback();     // 交给真服务 / 已装的其它拦截
    const json = obj => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(obj) });
    switch (p){
      case '/api/settings':
        return json({ ok: true, version: state.version,
                      settings: { auto_check_update: false, auto_install: false },
                      checkInterval: 21600,
                      releasesUrl: 'https://github.com/DC1024/answer-sheet-builder/releases',
                      selfUpdateAvailable: state.selfUpdate });
      case '/api/update/progress':
        return json(Object.assign({ ok: true, running: false, done: false, error: '',
                                    version: '', progress: 0, total: 0, src: null },
                                  state.download || {}));
      case '/api/update/last-boot':
        return json({ ok: true, failure: state.lastBoot || null });
      case '/api/health':
        if (state.health === 'down')
          return route.fulfill({ status: 503, contentType: 'text/plain', body: 'down' });
        return json({ ok: true, version: state.health, needSetup: false, schema: 1,
                      cnn: { ready: true }, engine: {} });
      case '/api/update':
        return json({ ok: true, current: state.version, latest: state.latest, hasUpdate: true,
                      url: 'https://github.com/DC1024/answer-sheet-builder/releases/tag/'
                           + state.latest,
                      name: state.latest, notes: '- 修了自更新', publishedAt: '',
                      publishedUrl: '', error: '',
                      selfUpdateAvailable: state.selfUpdate, autoInstall: false,
                      cached: false, checkedAt: Math.floor(Date.now() / 1000),
                      download: Object.assign({ running: false, done: false }, state.download || {}) });
      case '/api/update/install':
        state.installCalls++;
        if (state.installResponse === 'fail')
          return json({ ok: false, error: '引导程序 25 秒内没有响应（多半是没能启动）' });
        state.health = 'down';       // 服务随即开始重启
        return json({ ok: true, restarting: true, from: 'v' + state.version,
                      to: 'v' + String(state.latest).replace(/^v/, '') });
    }
  };
}

function baseState(over){
  return Object.assign({
    version: '1.4.1', latest: 'v1.4.2', selfUpdate: true, health: '1.4.1',
    download: { done: true, version: 'v1.4.2', src: 'C:/tmp/staged' },
    lastBoot: null, installCalls: 0, installResponse: 'ok',
  }, over || {});
}

// 打开一个页面：真登录拿 cookie → 落到「设置」页签。
// 会话 cookie 在同一个 context 里是共享的，所以只有第一次需要真的填表登录；
// 之后直接进首页即可（否则会白等 30 秒找 #u）。
let loggedIn = false;
async function openSet(ctx, state){
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  await page.route('**/api/**', makeBackend(state));
  if (!loggedIn){
    // `GET /` 在服务端要会话，所以必须先真登录一次
    await page.goto(BASE + '/login', { waitUntil: 'load' });
    await page.fill('#u', USER);
    await page.fill('#p', PW);
    await Promise.all([
      page.waitForURL(u => !/\/login/.test(String(u)), { timeout: 15000 }),
      page.click('#go'),
    ]);
    loggedIn = true;
  } else {
    await page.goto(BASE + '/', { waitUntil: 'load' });
  }
  await page.waitForSelector('#tabs .tab[data-page="set"]', { timeout: 15000 });
  await page.click('#tabs .tab[data-page="set"]');
  await page.waitForSelector('#setVer', { state: 'visible', timeout: 10000 });
  return { page, errors };
}

(async () => {
  if (!fs.existsSync(EXE)) throw new Error('找不到 Chromium：' + EXE + '（用 CHROME= 指定）');
  const browser = await chromium.launch({ args: ['--no-sandbox'], executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 } });

  // ---------------------------------------------------------------- A/B/C
  console.log('=== A/B/C. 设置页：版本号 + 查更新 + 自更新控件 ===');
  const st = baseState();
  const { page, errors } = await openSet(ctx, st);

  const verTxt = flat(await page.textContent('#setVer'));
  assert(verTxt === 'v1.4.1', '设置页显示当前版本号', verTxt);

  await page.click('#btnUpd');
  await sleep(700);
  const box1 = await page.evaluate(() => {
    const b = document.querySelector('#setUpdBox');
    return { hidden: b ? b.hidden : null, html: b ? b.innerHTML : '' };
  });
  assert(box1.hidden === false, '查到新版本 → 结果框显示出来');
  assert(/1\.4\.2/.test(box1.html), '结果框里写明新版本号 1.4.2', flat(box1.html).slice(0, 80));

  const a3 = await page.evaluate(() => {
    const g = id => document.querySelector(id);
    return { actions: g('#updActions') ? g('#updActions').hidden : null,
             instHidden: g('#btnInstall') ? g('#btnInstall').hidden : null,
             instText: g('#btnInstall') ? g('#btnInstall').textContent.trim() : '',
             dlHidden: g('#btnDlUpd') ? g('#btnDlUpd').hidden : null };
  });
  assert(a3.actions === false, '支持自更新 → 展示自更新控件');
  assert(a3.instHidden === false && /安装并重启/.test(a3.instText),
    '已下载好暂存包 → 直接显示「安装并重启」（不必再下载一次）',
    a3.instText + ' / dl.hidden=' + a3.dlHidden);
  // tag 自带 v 前缀，拼字符串时容易拼出 "vv1.4.2" —— 单纯「有没有字」的断言看不出来
  assert(!/vv/i.test(a3.instText), '版本号没有拼重（不会出现「安装并重启 vv1.4.2」）',
    a3.instText);
  await shot(page, 'upd-1-有更新可安装');

  // ---------------------------------------------------------------- D
  console.log('\n=== D. 点「安装并重启」→ 服务重启 → 新版本起来 → 自动刷新 ===');
  let reloads = 0;
  page.on('framenavigated', fr => { if (fr === page.mainFrame()) reloads++; });
  const before = reloads;
  await page.click('#btnInstall');
  await sleep(1400);
  // 刚点下去时提示在 toast 上；等久一点会移到 #setUpdInfo。两处都算数。
  const mid = flat(await page.textContent('#setUpdInfo')) + ' '
            + flat(await page.textContent('#toast'));
  assert(st.installCalls === 1, '安装接口被调用了一次', 'calls=' + st.installCalls);
  assert(/等待|安装|重启/.test(mid), '点后给出「正在等待新版本启动」之类的进度提示', mid.slice(0, 90));
  assert(st.health === 'down', '服务已进入重启中（连不上）');
  await shot(page, 'upd-2-等待新版本启动');

  // 服务以**新版本号**回来 → 前端应在轮询发现后自己刷新
  st.health = '1.4.2';
  await sleep(7000);
  assert(reloads > before, '**版本号真的变了之后才刷新页面**（而不是盲等固定秒数）',
    'reloads=' + (reloads - before));
  await page.close();

  // ---------------------------------------------------------------- E
  console.log('\n=== E. 服务活着、但版本没换成新版 → 必须说清楚 ===');
  const st2 = baseState();
  const r2 = await openSet(ctx, st2);
  await r2.page.click('#btnInstall');       // 服务变 down
  await sleep(700);
  st2.health = '1.4.1';                     // 窗口起来了，但**还是旧版本**
  await sleep(9000);
  const said2 = await r2.page.evaluate(() => ({
    info: (document.querySelector('#setUpdInfo') || {}).textContent || '',
    toast: (document.querySelector('#toast') || {}).textContent || '',
  }));
  const flat2 = flat(said2.info + ' ' + said2.toast);
  assert(/未换成|仍是|没有生效/.test(flat2),
    '**明确说出「服务已重启但版本没变」**（而不是沉默或谎报成功）', flat2.slice(0, 110));
  // 这条是给「内部报错被 catch 吞掉」设的哨兵：曾经 waitForRestart 里引用了作用域外的
  // `inst`，抛出的 ReferenceError 被 installUpdate 的 catch 吞成一句「安装请求失败」——
  // 页面上没有 pageerror，于是「无 JS 错误」那条照样绿，只有肉眼看截图才能发现。
  assert(!/请求失败|is not defined/.test(flat2),
    '上面那句是真的走到「版本没换」这条分支，而不是内部报错被 catch 吞了',
    flat2.slice(0, 110));
  const btn2 = await r2.page.evaluate(() =>
    (document.querySelector('#btnInstall') || {}).disabled);
  assert(btn2 === false, '按钮恢复可点，老师能再试一次');
  await shot(r2.page, 'upd-3-版本没换成');
  await r2.page.close();

  // ---------------------------------------------------------------- F
  console.log('\n=== F. 装失败（引导程序没起来）→ 原因要显示出来 ===');
  const st3 = baseState({ installResponse: 'fail' });
  const r3 = await openSet(ctx, st3);
  await r3.page.click('#btnInstall');
  await sleep(1600);
  const t3 = flat(await r3.page.textContent('#toast'));
  assert(/引导程序/.test(t3), '把服务端给的失败原因显示出来了（不是只说「失败」）', t3.slice(0, 90));
  const btn3 = await r3.page.evaluate(() =>
    (document.querySelector('#btnInstall') || {}).disabled);
  assert(btn3 === false, '失败后按钮恢复可点');
  await shot(r3.page, 'upd-4-安装失败原因');
  await r3.page.close();

  // ---------------------------------------------------------------- G
  console.log('\n=== G. 上次引导程序崩过 → 界面要看得到（不能永远静默）===');
  const st4 = baseState({ download: { done: false },
    lastBoot: { version: 'v1.4.2', exitCode: 3221225781,
                error: 'Failed to load Python DLL ...python313.dll' } });
  const r4 = await openSet(ctx, st4);
  await sleep(1500);
  const box4 = await r4.page.evaluate(() => ({
    hidden: (document.querySelector('#setUpdBox') || {}).hidden,
    html: (document.querySelector('#setUpdBox') || {}).innerHTML || '',
    info: (document.querySelector('#setUpdInfo') || {}).textContent || '',
  }));
  const flat4 = flat(box4.html + ' ' + box4.info);
  assert(/没有装成功|没装成功|失败/.test(flat4), '**上次失败的事故显示在界面上**', flat4.slice(0, 100));
  assert(/Python DLL|3221225781/.test(flat4), '带上技术细节，便于排查', flat4.slice(0, 100));
  await shot(r4.page, 'upd-5-上次失败记录');
  await r4.page.close();

  // ---------------------------------------------------------------- H
  console.log('\n=== H. 源码/容器环境不支持自更新 → 不显示安装控件 ===');
  const st5 = baseState({ selfUpdate: false, download: { done: false } });
  const r5 = await openSet(ctx, st5);
  await r5.page.click('#btnUpd');
  await sleep(800);
  const a5 = await r5.page.evaluate(() =>
    (document.querySelector('#updActions') || {}).hidden);
  assert(a5 === true, '不支持自更新时不显示下载/安装控件（只留去发行版页面手动下载）');
  await r5.page.close();

  // ---------------------------------------------------------------- I
  console.log('\n=== I. 页面无 JS 错误 ===');
  const allErr = errors.concat(r2.errors, r3.errors, r4.errors, r5.errors);
  assert(allErr.length === 0, '整轮下来没有页面 JS 错误', allErr.slice(0, 3).join(' | '));

  await browser.close();
  console.log('\n' + '='.repeat(56));
  console.log('通过 ' + PASS + ' 项，失败 ' + FAILS + ' 项');
  if (FAILS) process.exit(1);
  console.log('🎉 设置 / 检查更新 / 自更新面板 UI 验证全部通过');
})().catch(e => { console.error(e); process.exit(1); });