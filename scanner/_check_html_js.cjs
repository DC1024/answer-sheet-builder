// 校验 index.html 里 <script> 块的 JS 语法（单文件 HTML 尾部重复代码的坑 → vm.Script parse 兜底）
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync(process.argv[2], 'utf-8');
const m = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if (!m.length){ console.log('NO SCRIPT BLOCK'); process.exit(1); }
let bad = 0;
m.forEach((x, i) => {
  try { new vm.Script(x[1], {filename: `block${i}`}); console.log(`block${i}: OK (${x[1].length} chars)`); }
  catch (e) { bad++; console.log(`block${i}: SYNTAX ERROR -> ${e.message}`); }
});
process.exit(bad ? 1 : 0);