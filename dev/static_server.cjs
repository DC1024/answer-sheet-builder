const http = require('http');
const fs = require('fs');
const path = require('path');
// 硬编码仓库根：绕开 bash 对 Windows 盘符路径 argv/cwd 的转换
const ROOT = 'C:/Users/15657.DC-PC/WorkBuddy/2026-09-24-19-34-04/answer-sheet-builder';
const PORT = parseInt(process.env.PORT || '8080', 10);
const MIME = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.json':'application/json', '.png':'image/png', '.svg':'image/svg+xml', '.ico':'image/x-icon' };
http.createServer((req, res) => {
  let u = decodeURIComponent((req.url || '/').split('?')[0]);
  if (u === '/' || u === '') u = '/app.html';
  const rel = u.replace(/^[/\\]+/, '');            // 去掉前导 /，避免 Windows path.join 重置盘符
  const p = path.resolve(ROOT, rel);
  if (p !== path.resolve(ROOT) && !p.startsWith(path.resolve(ROOT) + path.sep)) {
    res.writeHead(403); return res.end('forbidden');
  }
  fs.readFile(p, (err, data) => {
    if (err) { res.writeHead(404); return res.end('404'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(p).toLowerCase()] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(PORT, () => console.log('static on ' + PORT + ' root=' + ROOT));
