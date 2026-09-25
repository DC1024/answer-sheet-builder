// 端到端验证：制卡端导出的 writebox 模板 → 扫描端 decode_write 识别。
// 打开真实 app.html，通过动态 import 拿 store，构造一个 writebox 选择题块，
// exportOmrTemplate 导出模板，断言 questions[] 含 write 坐标；再把模板喂给
// Python 端 omr 走整条手写识别链路。
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const BASE = process.env.BASE || 'http://127.0.0.1:8080';
const URL = BASE + '/app.html';
const ROOT = __dirname;
const EXE = path.join(process.env.LOCALAPPDATA || '', 'ms-playwright',
  'chromium-1234', 'chrome-win64', 'chrome.exe');
const PY = path.join(__dirname, 'scanner', '.venv', 'Scripts', 'python.exe');
const FIX = path.join(__dirname, 'scanner', 'tests', 'fixtures', 'real30');
const OUT_TEMPLATE = path.join(FIX, 'builder_writebox_template.json');
const OUT_SHEET = path.join(FIX, 'builder_writebox_sheet.png');

function assert(cond, msg){
  if (!cond){ console.error('✗ ' + msg); process.exit(1); }
  console.log('✓ ' + msg);
}

(async () => {
  const browser = await chromium.launch({
    args: ['--no-sandbox'], executablePath: fs.existsSync(EXE) ? EXE : undefined
  });
  const page = await browser.newPage({ viewport: { width: 1400, height: 2000 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(URL, { waitUntil: 'load' });

  // 动态 import store，清空现有块，加一个 writebox 选择题块
  const built = await page.evaluate(async () => {
    const store = (await import('/assets/js/core/store.js')).store;
    const registry = (await import('/assets/js/core/registry.js')).registry;
    const mod = registry.get('singleChoice');
    // 清空
    store.blocks = [];
    const cfg = mod.defaults();
    cfg.title = '一、手写选择题（请在方框内写 A/B/C/D）';
    cfg.count = 6; cfg.options = 4; cfg.mode = 'writebox'; cfg.hwGap = 5;
    store.addBlock('singleChoice', cfg);
    return { blocks: store.blocks.length, mode: store.blocks[0].config.mode };
  });
  console.log('构造块:', built);
  assert(built.mode === 'writebox', '选择题块已切到 writebox 样式');

  // 触发渲染
  await page.evaluate(() => { window.dispatchEvent(new Event('resize')); });
  await page.waitForTimeout(300);

  // 截图看渲染效果
  const sheet = await page.$('#sheet');
  assert(sheet, '#sheet 存在');
  await sheet.screenshot({ path: OUT_SHEET });
  console.log('渲染截图已存', OUT_SHEET);

  // 导出模板
  const tpl = await page.evaluate(async () => {
    const { exportOmrTemplate } = await import('/assets/js/core/omr.js');
    const t = exportOmrTemplate(document.getElementById('sheet'));
    t._wboxRendered = !!document.querySelector('#sheet .wb .wbox');
    t._qRendered = document.querySelectorAll('#sheet .scq').length;
    return t;
  });
  assert(!errors.length, '无页面 JS 错误（' + (errors.length ? errors[0] : '') + ')');
  assert(tpl._wboxRendered, `writebox 方框已渲染（共 ${tpl._qRendered} 题）`);
  const wq = (tpl.pages || []).flatMap(p => p.questions || []).filter(q => q.write);
  const bq = (tpl.pages || []).flatMap(p => p.questions || []).filter(q => q.options);
  console.log(`  writebox 题: ${wq.length}, bubble 题: ${bq.length}`);
  assert(wq.length === 6, `导出 6 道 write 题（实际 ${wq.length}）`);
  assert(bq.length === 0, '无多余 options 题');
  const w0 = wq[0];
  assert(w0.write && [w0.write.x, w0.write.y, w0.write.w, w0.write.h].every(v => v > 0),
    `write 坐标齐全: ${JSON.stringify(w0.write)}`);

  fs.writeFileSync(OUT_TEMPLATE, JSON.stringify(tpl, null, 2));
  console.log('模板已写', OUT_TEMPLATE);

  await browser.close();

  // 端到端：Python 端加载该模板，对真实扫描图做一次手写整卷识别
  // 直接在 builder 模板的 write 坐标上验证 decode_write 兼容
  console.log('\n--- 扫描端 decode_write 链路（builder 模板） ---');
  try {
    const out = execFileSync(PY, ['-c', `
import sys, json, os, cv2, numpy as np
sys.path.insert(0, '.')
from app import omr
FIX='tests/fixtures/real30'
tpl=json.load(open(os.path.join(FIX,'builder_writebox_template.json'),encoding='utf-8'))
tpl=omr.load_template(json.dumps(tpl))
# 确认模板格式和 write 字段能过 load_template
print('format', tpl['format'], 'write题', sum(1 for p in tpl['pages'] for q in p.get('questions',[]) if q.get('write')))
# 直接构造一份手写整卷图：在 write 框坐标写字
bgr=cv2.imdecode(np.fromfile(os.path.join(FIX,'第01份_张一鸣_01.png'),dtype=np.uint8),cv2.IMREAD_COLOR)
quad,_=omr.detect_marks(bgr,tpl); warp,px=omr.warp_page(bgr,quad,tpl,px_per_mm=15.11)
work=warp.copy()
answers='ADBDDACACA'
for q in [q for p in tpl['pages'] for q in p.get('questions',[]) if q.get('write')]:
    w=q['write']; cx,cy=int(w['x']*px),int(w['y']*px); fs=w['h']*px*0.8
    cv2.putText(work,answers[q['no']-1],(cx-int(fs*0.35),cy+int(fs*0.5)),cv2.FONT_HERSHEY_SIMPLEX,fs/32.0,(0,0,0),max(3,int(px*0.13)),cv2.LINE_AA)
work=cv2.dilate(work,np.ones((3,3),np.uint8),iterations=1)
out=omr.recognize(work,tpl,overlay=False)
wres={r['no']:r for r in out['questions'] if r.get('x') is not None}
got=''.join(str(wres[i]['answer']) if i in wres and wres[i]['answer'] else '?' for i in range(1,7))
print('builder 模板手写整卷识别:', got, '/ 真值 ADBDDA')
n_ok=sum(1 for i in range(1,7) if i in wres and wres[i].get('answer')==answers[i-1])
print('正确', n_ok, '/6, 自信错', sum(1 for i in range(1,7) if i in wres and wres[i].get('answer') and wres[i]['answer']!=answers[i-1]))
assert n_ok>=3, 'builder 模板手写链路应可识别'
print('e2e OK')
`], { encoding: 'utf8' });
    console.log(out);
  } catch (e) {
    console.error('Python e2e 失败:', e.stdout?.slice(-600) || e.message);
    process.exit(1);
  }
  console.log('\n🎉 writebox 端到端验证通过');
})().catch(e => { console.error(e); process.exit(1); });