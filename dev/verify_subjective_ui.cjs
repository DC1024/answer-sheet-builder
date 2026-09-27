// 端到端验证（主观题阅卷工作台 UI）：真服务 + 真浏览器点一遍。
//
// 前置：先由 dev/seed_subjective_ui.py 造好数据并起服务（默认 http://127.0.0.1:8199）。
// 为什么必须有这一层：后端 test_subjective.py 全绿，但页面完全可能把「客观/主观/总分」
// 排错列、把打分框绑到别的题、切「整页」时图还是旧的那张 —— 这些后端一个都测不到。
//
// 断言清单（每条都对应一个「老师会当场发火」的具体场景）：
//   A 登录后阅卷页有 3 个人；表头是 客观分/主观分/总分（不是老的 原始分/复核分）
//   B 打开复核弹窗：2 张主观题卡片、第 21 题 2 个小问、第 22 题 1 个整题输入框
//   C 右侧默认显示第 21 题的【裁剪图】（/api/region/...），不是整页
//   D 输入小问得分 → 卡片小计 / 弹窗合计预览 / 表格三列 全部同步
//   E 切「整页校对」→ 图换成 /api/overlay/...；切回 → 又是裁剪图
//   F 保存 → 重新打开复核，分数还在（真的落库了，不是只存在内存里）
//   G 复核分覆盖：填数字后合计以它为准，清空后回到 客观＋主观
//   H 主观题不打分时不该算 0 分进总分 —— 应为「待阅卷」（后端 verdict 已保证，这里看 UI 呈现）
//
// 用法：
//   NODE_PATH=<node_modules> node dev/verify_subjective_ui.cjs
//   环境变量：BASE / CHROME / PORT
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || '8199';
const BASE = process.env.BASE || ('http://127.0.0.1:' + PORT);
const EXE = process.env.CHROME || path.join(process.env.LOCALAPPDATA || '', 'ms-playwright',
  'chromium-1234', 'chrome-win64', 'chrome.exe');
const USER = process.env.ADMIN_USER || 'uiadmin';
const PW = process.env.ADMIN_PW || 'uitest12345';
// 顺手留两张图：出问题时比一行 "x 表格总分列 32/35" 有用得多，
// 也能直接拿来贴 issue / 放进发布说明。落在 gitignore 掉的 dev/.cache 下。
const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, '.cache', 'shots');

let FAILS = 0, PASS = 0;
function assert(cond, msg, extra){
  if (!cond){ FAILS++; console.error('  x ' + msg + (extra ? '  ' + extra : '')); }
  else { PASS++; console.log('  v ' + msg + (extra ? '  ' + extra : '')); }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

// 截图失败绝不该让验证变红 —— 它只是附件，不是断言。
async function shot(page, name){
  try {
    fs.mkdirSync(SHOT_DIR, { recursive: true });
    const p = path.join(SHOT_DIR, name + '.png');
    await page.screenshot({ path: p, fullPage: false });
    console.log('  （截图）' + p);
  } catch (e) { console.log('  （截图失败，忽略）' + e.message); }
}

(async () => {
  if (!fs.existsSync(EXE)) throw new Error('找不到 Chromium：' + EXE + '（用 CHROME= 指定）');
  const browser = await chromium.launch({ args: ['--no-sandbox'], executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [], http4xx = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  page.on('response', r => {
    if (r.status() >= 400) http4xx.push(r.status() + ' ' + r.url().replace(BASE, ''));
  });

  console.log('=== 0. 登录 ===');
  await page.goto(BASE + '/login', { waitUntil: 'load' });
  await page.fill('#u', USER);
  await page.fill('#p', PW);
  await Promise.all([
    page.waitForURL(u => !/\/login/.test(String(u)), { timeout: 15000 }),
    page.click('#go'),
  ]);
  assert(!/\/login/.test(page.url()), '登录成功并跳离 /login', page.url());
  await page.waitForSelector('#tabs .tab', { timeout: 10000 });

  console.log('\n=== 0b. 清掉上一轮跑剩的复核结果（让这个脚本可以反复跑）===');
  // 这个脚本自己会保存复核（F 段），所以第二次跑的时候库里已经有分了。
  // 与其要求「先删数据目录再跑」（谁都会忘，忘了就得到一串莫名其妙的红），
  // 不如自己先把状态抹平 —— 用页面里的登录态直接打接口。
  const reset = await page.evaluate(async () => {
    const gj = await (await fetch('/api/gradebook', { credentials: 'same-origin' })).json();
    const sids = (gj.students || []).map(s => s.sid);
    const out = [];
    for (const sid of sids){
      const r = await fetch('/api/grade', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sid, grading: {
          overrides: {}, scores: {}, subs: {}, manualScore: null, review: false, note: '' } }),
      });
      out.push(sid + ':' + r.status);
    }
    return out;
  });
  assert(reset.length > 0 && reset.every(x => x.endsWith(':200')),
    '上一轮的复核结果已清空（脚本可反复跑）', reset.join(' '));

  console.log('\n=== A. 阅卷页：三个人 + 三列表头 ===');
  await page.click('#tabs .tab[data-page="grade"]');
  await page.click('#gbRefresh');
  await page.waitForSelector('#gbBody table tbody tr', { timeout: 15000 });
  const rows = await page.$$eval('#gbBody tbody tr', trs => trs.length);
  assert(rows === 2, '表里 2 行（名单 3 人、只有 2 张卷子）', '实测 ' + rows);
  const head = await page.$$eval('#gbBody thead th', ths => ths.map(t => t.textContent.trim()));
  assert(head.join('|') === '考号|姓名|班级|客观分|主观分|总分|标注|操作',
    '表头是 客观分/主观分/总分', head.join('|'));
  const sumTxt = await page.textContent('#gbSum');
  assert(/满分：客观 19(\.0)? ＋ 主观 16(\.0)? ＝ 35(\.0)?/.test(sumTxt),
    '汇总条写明 满分 客观19+主观16=35', sumTxt.trim());
  // 主观分为 0 的（还没阅）应显示为灰字 hint，而不是像「真的 0 分」那样扎眼
  const subCell = await page.$eval('#gbBody tbody tr td:nth-child(5)', td => td.innerHTML);
  assert(/hint/.test(subCell), '未阅卷的主观分是灰色提示样式', subCell.trim().slice(0, 60));
  console.log('\n=== B. 打开复核弹窗：主观题卡片结构 ===');
  await page.click('#gbBody tbody tr:first-child button[data-sid]');
  await page.waitForSelector('#gbModal.on', { timeout: 10000 });
  const cards = await page.$$('#gbModalBody .subcard');
  assert(cards.length === 2, '两张主观题卡片（21 / 22）', '实测 ' + cards.length);
  const qs = await page.$$eval('#gbModalBody .subcard', cs => cs.map(c => c.dataset.subq));
  assert(qs.join(',') === '21,22', '题号顺序是 21,22', qs.join(','));
  const in21 = await page.$$eval('.subcard[data-subq="21"] .subin',
    is => is.map(i => ({ q: i.dataset.q, i: i.dataset.i, max: i.max })));
  assert(in21.length === 2 && in21[0].i === '0' && in21[1].i === '1',
    '第 21 题按小问给分：2 个输入框（i=0/1）', JSON.stringify(in21));
  assert(in21[0].max === '4' && in21[1].max === '6',
    '两个小问的满分分别是 4 / 6', JSON.stringify(in21.map(x => x.max)));
  const in22 = await page.$$eval('.subcard[data-subq="22"] .subin',
    is => is.map(i => ({ i: i.dataset.i, max: i.max })));
  assert(in22.length === 1 && in22[0].i === '-1' && in22[0].max === '6',
    '第 22 题整题给分：1 个输入框（i=-1），满分 6', JSON.stringify(in22));
  // 客观题列表里不该再出现主观题（否则老师会以为 21 题也要读卡）
  const objQnos = await page.$$eval('#gbModalBody .gbq .qrow .qno',
    ss => ss.map(s => s.textContent.replace(/\D+/g, ' ').trim().split(/\s+/)[0]));
  assert(!objQnos.includes('21') && !objQnos.includes('22'),
    '逐题改答案列表里没有主观题', objQnos.join(','));

  console.log('\n=== C. 右侧默认显示第 21 题的裁剪图 ===');
  let src = await page.getAttribute('#gbImg', 'src');
  assert(/^\/api\/region\/[0-9a-z]+\/21\.jpg$/.test(String(src)),
    '默认 src 是 /api/region/<rid>/21.jpg', String(src));
  const segOn = await page.$$eval('#gbSeg button.on', bs => bs.map(b => b.textContent.trim()));
  assert(segOn.join('') === '当前题裁剪', '分段控件高亮在「当前题裁剪」', segOn.join(''));
  const cardOn = await page.$$eval('#gbModalBody .subcard.on', cs => cs.map(c => c.dataset.subq));
  assert(cardOn.join(',') === '21', '第 21 题卡片是选中态', cardOn.join(','));
  // 裁剪图要真的能加载出来（200 + 有像素）
  const cropOk = await page.evaluate(async () => {
    const im = document.querySelector('#gbImg');
    if (!im.complete) await new Promise(r => { im.onload = r; im.onerror = r; });
    return { w: im.naturalWidth, h: im.naturalHeight, ok: im.naturalWidth > 0 };
  });
  assert(cropOk.ok, '裁剪图真的加载出了像素', JSON.stringify(cropOk));

  console.log('\n=== C2. 两列真并排 + 卡片里的裁剪图不许撑破左列 ===');
  // 这是量出来的，不是看出来的。主观题卡片里多了一张裁剪图，而 CSS Grid 的网格项默认
  // min-width:auto —— 一张原图宽 1505px 的裁剪图足以把左列顶宽、把右列挤出去，
  // 或者干脆糊在右列底下（v1.3.2 修过一次同类「并排/错位」）。眼睛在小图上很难判断，
  // 所以这里直接比矩形。
  const geo = await page.evaluate(() => {
    const body = document.querySelector('#gbModalBody');
    const col = body.querySelector('.gbqcol');
    const pane = body.querySelector('.gbimgcol');
    const over = el => {
      const pr = el.parentElement.getBoundingClientRect();
      return +(el.getBoundingClientRect().right - pr.right).toFixed(2);
    };
    return {
      colRight: +col.getBoundingClientRect().right.toFixed(2),
      paneLeft: +pane.getBoundingClientRect().left.toFixed(2),
      cropOver: [...body.querySelectorAll('.scrop')].map(over),
      // 卡片里任何一个后代超出卡片右边多少（负=没超）
      cardOver: [...body.querySelectorAll('.subcard')].map(c => {
        const cr = c.getBoundingClientRect();
        return +[...c.querySelectorAll('*')]
          .reduce((m, el) => Math.max(m, el.getBoundingClientRect().right - cr.right), 0).toFixed(2);
      }),
      bodyOver: body.scrollWidth - body.clientWidth,
    };
  });
  assert(geo.paneLeft >= geo.colRight - 1,
    '左列（题目）与右列（阅卷图）真的并排、不重叠',
    `colRight=${geo.colRight} paneLeft=${geo.paneLeft}`);
  assert(geo.cropOver.every(v => v <= 1), '裁剪图没有超出所在卡片（max-width:100% 真的生效）',
    JSON.stringify(geo.cropOver));
  assert(geo.cardOver.every(v => v <= 1), '卡片里没有后代溢出卡片右边界',
    JSON.stringify(geo.cardOver));
  assert(geo.bodyOver <= 1, '弹窗内容区没有横向溢出（不出现横向滚动条）', String(geo.bodyOver));

  console.log('\n=== D. 打小问分 → 小计 / 合计预览 / 表格同步 ===');
  await page.fill('.subcard[data-subq="21"] .subin[data-i="0"]', '4');
  await page.fill('.subcard[data-subq="21"] .subin[data-i="1"]', '6');
  await sleep(120);
  const tot21 = (await page.textContent('[data-subtot="21"]')).trim();
  assert(/^10(\.0)? \/ 10(\.0)?$/.test(tot21), '第 21 题小计 = 10 / 10', tot21);
  const cls21 = await page.getAttribute('[data-subtot="21"]', 'class');
  assert(/done/.test(cls21), '满分小计是「做完」配色', cls21);
  await page.fill('.subcard[data-subq="22"] .subin[data-i="-1"]', '3');
  await sleep(120);
  let pv = (await page.textContent('#gbPreview')).trim();
  assert(/客观 19(\.0)? ＋ 主观 13(\.0)? ＝ 32(\.0)? \/ 35(\.0)?/.test(pv),
    '合计预览 = 客观19 + 主观(10+3) = 32 / 35', pv);
  await shot(page, '2-grading-modal');
  // 超满分要夹住（老师手滑打了 60）
  await page.fill('.subcard[data-subq="22"] .subin[data-i="-1"]', '60');
  await sleep(120);
  pv = (await page.textContent('#gbPreview')).trim();
  assert(/主观 16(\.0)? ＝ 35(\.0)?/.test(pv), '第 22 题打 60 分被夹到满分 6（合计 35）', pv);
  const cls22 = await page.getAttribute('[data-subtot="22"]', 'class');
  assert(/done/.test(cls22), '夹到满分后小计是「做完」配色', cls22);
  await page.fill('.subcard[data-subq="22"] .subin[data-i="-1"]', '3');
  await sleep(120);

  console.log('\n=== E. 裁剪 / 整页 切换 ===');
  await page.click('#gbSeg button[data-gbmode="page"]');
  await sleep(150);
  src = await page.getAttribute('#gbImg', 'src');
  assert(/^\/api\/overlay\/[0-9a-z]+\.png$/.test(String(src)),
    '切「整页校对」→ /api/overlay/<rid>.png', String(src));
  const segOn2 = await page.$$eval('#gbSeg button.on', bs => bs.map(b => b.textContent.trim()));
  assert(segOn2.join('') === '整页校对', '分段控件高亮切到「整页校对」', segOn2.join(''));
  await shot(page, '3-fullpage-mode');
  await page.click('#gbSeg button[data-gbmode="crop"]');
  await sleep(150);
  src = await page.getAttribute('#gbImg', 'src');
  assert(/\/api\/region\/[0-9a-z]+\/21\.jpg$/.test(String(src)),
    '切回「当前题裁剪」→ 又是第 21 题的裁剪图', String(src));
  // 点第 22 题卡片 → 图切到 22；再点一次 → 回整页
  await page.click('.subcard[data-subq="22"] .shd');
  await sleep(150);
  src = await page.getAttribute('#gbImg', 'src');
  assert(/\/api\/region\/[0-9a-z]+\/22\.jpg$/.test(String(src)),
    '点第 22 题卡片 → 图切到 22 题裁剪', String(src));
  await page.click('.subcard[data-subq="22"] .shd');
  await sleep(150);
  src = await page.getAttribute('#gbImg', 'src');
  assert(/\/api\/overlay\//.test(String(src)), '同一张卡片再点一次 → 回整页', String(src));
  await page.click('.subcard[data-subq="21"] .shd');
  await sleep(120);

  console.log('\n=== G. 复核分覆盖 ===');
  await page.fill('#gbManual', '30');
  await sleep(120);
  pv = (await page.textContent('#gbPreview')).trim();
  assert(/^30(\.0)? \/ 35(\.0)?（复核分覆盖/.test(pv), '填复核分 30 → 合计以它为准，并说明覆盖了什么', pv);
  await page.fill('#gbManual', '');
  await sleep(120);
  pv = (await page.textContent('#gbPreview')).trim();
  assert(/^客观 19(\.0)? ＋ 主观 13(\.0)?＝? ?＝ 32(\.0)?|客观 19(\.0)? ＋ 主观 13(\.0)?/.test(pv),
    '清空复核分 → 回到 客观＋主观', pv);
  // 复核分是手滑打的 999 也要夹吗？—— 不夹，这是老师明确要的总分，只在库里保证有限数
  await page.fill('#gbManual', '999');
  await sleep(100);
  pv = (await page.textContent('#gbPreview')).trim();
  assert(/999/.test(pv), '复核分是明确覆盖，不夹到满分（999 照显）', pv);
  await page.fill('#gbManual', '');
  await sleep(100);

  console.log('\n=== F. 保存 → 重开复核，分数还在 ===');
  await page.check('#gbReview');
  await page.fill('#gbNote', '第21题步骤完整；第22题结论对');
  await page.click('#gbSave');
  await page.waitForSelector('#gbModal.on', { state: 'detached', timeout: 10000 }).catch(() => {});
  await sleep(600);
  const rowCells = await page.$$eval('#gbBody tbody tr:first-child td',
    tds => tds.map(t => t.textContent.trim()));
  assert(rowCells[3] === '19/19', '表格客观分列 19/19', JSON.stringify(rowCells.slice(0, 6)));
  assert(rowCells[4] === '13/16', '表格主观分列 13/16', JSON.stringify(rowCells.slice(0, 6)));
  assert(rowCells[5] === '32/35', '表格总分列 32/35', JSON.stringify(rowCells.slice(0, 6)));
  assert(/待复核/.test(rowCells[6] || ''), '表格标注列显示了「待复核」', rowCells[6]);
  // 这一张最有代表性：客观 19/19、主观 13/16、总分 32/35，三列都有真数
  await shot(page, '1-gradebook');

  await page.click('#gbBody tbody tr:first-child button[data-sid]');
  await page.waitForSelector('#gbModal.on', { timeout: 10000 });
  const re21 = await page.$$eval('.subcard[data-subq="21"] .subin', is => is.map(i => i.value));
  const re22 = await page.$eval('.subcard[data-subq="22"] .subin', i => i.value);
  assert(re21.join(',') === '4,6', '重开后第 21 题两个小问的分还在', re21.join(','));
  assert(re22 === '3', '重开后第 22 题的分还在', re22);
  const note = await page.inputValue('#gbNote');
  assert(note === '第21题步骤完整；第22题结论对', '重开后备注还在', note);
  const reviewChecked = await page.isChecked('#gbReview');
  assert(reviewChecked, '重开后「标记待复核」还是勾着的');

  console.log('\n=== H. 未阅卷的主观分不计入总分 ===');
  // 找没阅过的那位（第二行），打开看：主观分应为 0，总分 = 客观分本身
  const secondSid = await page.$eval('#gbBody tbody tr:nth-child(2) button[data-sid]',
    b => b.dataset.sid);
  await page.click('#gbClose');
  await page.click(`#gbBody tbody tr:nth-child(2) button[data-sid]`);
  await page.waitForSelector('#gbModal.on', { timeout: 10000 });
  const pv2 = (await page.textContent('#gbPreview')).trim();
  const m2 = /客观 (\S+) ＋ 主观 (\S+) ＝ (\S+) \/ 35/.exec(pv2);
  assert(!!m2, '第二份卷子的合计预览格式正确', pv2);
  if (m2){
    assert(parseFloat(m2[2]) === 0, '没打分时主观分是 0', m2[2]);
    assert(Math.abs(parseFloat(m2[3]) - parseFloat(m2[1])) < 1e-6,
      '总分 = 客观分（没有任何主观分混进来）', JSON.stringify(m2.slice(1)));
  }
  const v22 = await page.$eval('.subcard[data-subq="22"] .subin', i => i.value);
  assert(v22 === '', '没打过分的输入框是空的（不是「0」）', JSON.stringify(v22));
  const clsEmpty = await page.getAttribute('[data-subtot="22"]', 'class');
  assert(/zero/.test(clsEmpty), '未打分的小计是「零分」配色（提示还没阅）', clsEmpty);
  // 分号带小数也要能存
  await page.fill('.subcard[data-subq="21"] .subin[data-i="0"]', '2.5');
  await sleep(150);
  pv = (await page.textContent('#gbPreview')).trim();
  assert(/主观 2\.5 /.test(pv), '小数分（2.5）能算进合计', pv);
  await page.click('#gbClose');

  console.log('\n=== 收尾：页面没报 JS 错 ===');
  const real4xx = http4xx.filter(u => !/favicon/.test(u));
  if (real4xx.length) console.log('  （提示，非失败）4xx：' + real4xx.join(' | '));
  assert(errors.length === 0, '控制台没有 JS 异常', errors.slice(0, 3).join(' || '));

  console.log('\n' + (FAILS ? `\u274c ${FAILS} 项失败 / ${PASS} 项通过` : `\u2705 全部通过（${PASS} 项）`));
  await browser.close();
  process.exit(FAILS ? 1 : 0);
})().catch(e => { console.error('\n脚本异常：' + (e && e.stack || e)); process.exit(2); });
