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
const SID_DIGITS = 10;   // 考号填涂区的位数

// 每个学生的答案（含 1 道空白、1 道浅涂、1 道涂两个，用来验证三种存疑标记）
// 后辍语法： 'A' 正常涂 / 'A:light' 浅涂 / null 不涂 / 'A:multi:B' 涂 A 再涂 B
const MULTI_Q = 15;
function answersFor(s){
  const out = {};
  for (let q = 1; q <= N_Q; q++){
    const r = (q * 7 + s * 3) % N_OPT;
    out[q] = 'ABCD'[r];
  }
  out[3] = null;                    // 未填
  out[8] = out[8] + ':light';       // 浅涂
  // 同一题涂两个选项（都够深）—— 「多选」是会覆盖学生答案的高风险判定，
  // 没有素材钉住它，second_rel_min 这类阈值改错了没人会发现。
  const mi = 'ABCD'.indexOf(out[MULTI_Q]);
  out[MULTI_Q] += ':multi:' + 'ABCD'[(mi + 1) % N_OPT];
  return out;
}

// 每个学生的考号（10 位）。s01~s03 会出现在测试用的名单里，s04 起故意不在名单里。
function sidFor(s){
  return String(2026010234 + s);
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

  const tpl = await page.evaluate(async ({ N_Q, N_OPT, SID_DIGITS }) => {
    const { store } = await import('./assets/js/core/store.js');
    const { registry } = await import('./assets/js/core/registry.js');
    const { renderPreview } = await import('./assets/js/core/preview.js');
    const { exportOmrTemplate } = await import('./assets/js/core/omr.js');
    store.paper = { size: 'A4', orientation: 'portrait', marks: 'square', markSize: 4 };
    store.blocks = [
      // 考生信息栏：开启考号填涂区 —— 扫描端就是靠它把考号从卷面上读出来的
      { id: 'c0', type: 'info', config: Object.assign(registry.get('info').defaults(),
        { examGrid: true, examDigits: SID_DIGITS }) },
      { id: 'c1', type: 'singleChoice', config: Object.assign(registry.get('singleChoice').defaults(),
        { title: '一、选择题', count: N_Q, cols: 5, options: N_OPT, mode: 'bubble', startNo: 1 }) }
    ];
    const sheet = document.getElementById('sheet');
    renderPreview(sheet);
    return exportOmrTemplate(sheet);
  }, { N_Q, N_OPT, SID_DIGITS });
  fs.writeFileSync(path.join(OUT, 'template.json'), JSON.stringify(tpl, null, 2));
  console.log('template.json：', tpl.questionCount, '题 /', tpl.pages.length, '面 /',
              'format', tpl.format, '/',
              tpl.sid ? `考号填涂 ${tpl.sid.digits} 位（第 ${tpl.sid.onPages.join(',')} 面）` : '无考号填涂区');
  if (!tpl.sid) throw new Error('素材里没有导出考号填涂区 —— 检查 info 区块的 examGrid 是否开启');

  const expected = { students: {},
    // 每份卷子都必须出现的存疑标记（与 omr.decide 的词表一致）
    questionEdges: { 3: 'blank', 8: 'faint', [MULTI_Q]: 'multi' } };
  for (let s = 0; s < STUDENTS; s++){
    const ans = answersFor(s);
    const sid = sidFor(s);
    const name = `s${String(s + 1).padStart(2, '0')}`;
    expected.students[name] = { sid, answers: {} };
    for (const q of Object.keys(ans)){
      const v = ans[q];
      expected.students[name].answers[q] = v === null ? null : String(v).split(':')[0];
    }
    await page.evaluate(async ({ ans, sid }) => {
      const sheet = document.getElementById('sheet');
      // 先清空上一次的填涂。boxShadow 必须一起清 —— 只清 background 会留下
      // 上一份卷子的阴影，表现为「没涂的圈检测出 0.85 的墨迹」。
      const wipe = b => {
        b.style.background = ''; b.style.borderColor = ''; b.style.color = '';
        b.style.borderRadius = ''; b.style.boxShadow = '';
      };
      sheet.querySelectorAll('.bub .bracket').forEach(wipe);
      sheet.querySelectorAll('.ebrk').forEach(wipe);        // 考号格同样要清

      const shade = (b, ink = '#2c2c2c') => {
        b.style.background = ink;
        b.style.borderColor = ink;
        b.style.color = ink;                 // 盖掉格子里的印刷数字
        b.style.borderRadius = '50%';
        b.style.boxShadow = `inset 0 0 0 12px ${ink}`;
      };
      // 灰度 → 归一化墨迹 ink ≈ (255-gray)/255：'#2c2c2c'≈0.83（实涂）、
      // '#9c9c9c'≈0.39（浅涂）、'#4a4a4a'≈0.71（第二个也涂得挺实，够触发 multi）
      for (const q of Object.keys(ans)){
        const v = ans[q];
        if (v === null) continue;
        const [letter, kind, altLetter] = String(v).split(':');
        const b = sheet.querySelector(`.scq[data-q="${q}"] .bub[data-opt="${letter}"] .bracket`);
        if (!b) continue;
        if (kind === 'light'){
          shade(b, '#9c9c9c');
        } else {
          shade(b);
          if (kind === 'multi' && altLetter){
            const b2 = sheet.querySelector(`.scq[data-q="${q}"] .bub[data-opt="${altLetter}"] .bracket`);
            if (b2) shade(b2, '#4a4a4a');
          }
        }
      }
      // 考号：逐位涂上对应数字的格子
      for (let i = 0; i < sid.length; i++){
        const b = sheet.querySelector(`.exam-grid[data-sid] .ebrk[data-pos="${i + 1}"][data-digit="${sid[i]}"]`);
        if (!b) throw new Error(`找不到考号第 ${i + 1} 位的数字格 ${sid[i]}`);
        shade(b);
      }
    }, { ans, sid });
    const el = await page.$('#sheet .page');
    await el.screenshot({ path: path.join(OUT, name + '.png') });
    console.log('  ->', name + '.png', '考号', sid);
  }

  // ---- 考号的边界情况 ----------------------------------------------------
  // 考号现在是「卷子归到谁名下」的唯一依据，错一位就等于把卷子归给别人。
  // 所以漏涂 / 浅涂 / 一列涂两个必须各有一张素材，且断言到「第几位」。
  // 文件用 x 前缀，不会被测试里 `s*` 的扫描范围捞进来。
  // variant = 素材上的物理形态（生成时怎么涂）；flag = decode_sid 应该报出的判定。
  // 两者分开写：以前只记 variant，测试脚本就得自己猜 'light' 该对应 'faint' 还是 'ok'，
  // 结果把「命名不一致」误当成「识别错了」。判定词表与 omr.decode_sid 保持一致。
  const EDGES = [
    { name: 'x1-blank', base: 0, variant: 'blank', flag: 'blank', pos: 3, why: '第 3 位故意不涂' },
    { name: 'x2-light', base: 1, variant: 'light', flag: 'faint', pos: 5, why: '第 5 位浅涂（中灰）' },
    { name: 'x3-multi', base: 2, variant: 'multi', flag: 'doubt', pos: 2, why: '第 2 位涂了两个数字' }
  ];
  expected.sidEdges = {};
  for (const e of EDGES){
    const ans = answersFor(e.base);
    const sid = sidFor(e.base);
    await page.evaluate(async ({ ans, sid, e }) => {
      const sheet = document.getElementById('sheet');
      const wipe = b => {
        b.style.background = ''; b.style.borderColor = ''; b.style.color = '';
        b.style.borderRadius = ''; b.style.boxShadow = '';
      };
      sheet.querySelectorAll('.bub .bracket').forEach(wipe);
      sheet.querySelectorAll('.ebrk').forEach(wipe);
      const shade = (b, ink = '#2c2c2c') => {
        b.style.background = ink; b.style.borderColor = ink; b.style.color = ink;
        b.style.borderRadius = '50%';
        b.style.boxShadow = `inset 0 0 0 12px ${ink}`;
      };
      // 答案照常涂（这些素材只考考号，选择题那部分与 s0x 同形即可）
      for (const q of Object.keys(ans)){
        const v = ans[q];
        if (v === null) continue;
        const [letter, kind, altLetter] = String(v).split(':');
        const b = sheet.querySelector(`.scq[data-q="${q}"] .bub[data-opt="${letter}"] .bracket`);
        if (b) shade(b, kind === 'light' ? '#9c9c9c' : '#2c2c2c');
        if (kind === 'multi' && altLetter){
          const b2 = sheet.querySelector(`.scq[data-q="${q}"] .bub[data-opt="${altLetter}"] .bracket`);
          if (b2) shade(b2, '#4a4a4a');
        }
      }
      for (let i = 0; i < sid.length; i++){
        const pos = i + 1;
        const digit = sid[i];
        if (e.variant === 'blank' && pos === e.pos) continue;             // 这一位不涂
        const b = sheet.querySelector(`.exam-grid[data-sid] .ebrk[data-pos="${pos}"][data-digit="${digit}"]`);
        if (!b) throw new Error(`找不到考号第 ${pos} 位的数字格 ${digit}`);
        shade(b, (e.variant === 'light' && pos === e.pos) ? '#9c9c9c' : '#2c2c2c');
        if (e.variant === 'multi' && pos === e.pos){
          // 再涂一个别的数字 → 两格一样深 → 判定为 doubt
          const alt = String((+digit + 5) % 10);
          const b2 = sheet.querySelector(`.exam-grid[data-sid] .ebrk[data-pos="${pos}"][data-digit="${alt}"]`);
          if (b2) shade(b2);
        }
      }
    }, { ans, sid, e });
    const el = await page.$('#sheet .page');
    await el.screenshot({ path: path.join(OUT, e.name + '.png') });
    // 期望读到的考号：漏涂那位留 '?'；一列涂两个时「选中哪个」本身无意义（两者一样深），
    // 所以只记候选集合，不钉死数字 —— 钉死了就是在测试里固化一个平局的偶然排序。
    const edge = { sid, pos: e.pos, variant: e.variant, flag: e.flag, why: e.why };
    if (e.variant === 'blank'){
      edge.text = sid.slice(0, e.pos - 1) + '?' + sid.slice(e.pos);
      edge.digit = null;
    } else if (e.variant === 'light'){
      edge.text = sid;
      edge.digit = sid[e.pos - 1];
    } else {
      edge.digitAny = [sid[e.pos - 1], String((+sid[e.pos - 1] + 5) % 10)].sort();
    }
    expected.sidEdges[e.name] = edge;
    console.log('  ->', e.name + '.png', e.why, '（考号', sid + '）');
  }

  fs.writeFileSync(path.join(OUT, 'expected.json'), JSON.stringify(expected, null, 2));
  await browser.close();
  console.log('素材生成完毕 ->', OUT);
})();
