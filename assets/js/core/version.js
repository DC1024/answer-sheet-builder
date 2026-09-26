// 版本号（制卡端）
//
// 制卡端是纯静态站点，没有 Python 可以去 import —— 版本号只能硬编码在这里。
// 扫描端在 `scanner/app/__init__.py` 的 `__version__`，**两份要一起改**
// （CHANGELOG 末尾的「发版清单」写了这件事）。
//
// `LATEST_API` 是更新检查的地址。GitHub 的 REST API 带 CORS 头
// （`Access-Control-Allow-Origin: *`），所以浏览器能直接跨域 GET ——
// 制卡端不需要任何后端就能查更新。代价是必须能上外网，内网/离线时只会
// 提示「暂时查不到」，不会报错。
export const APP_VERSION = '1.1.0';

export const REPO = 'DC1024/answer-sheet-builder';
export const RELEASES_URL = `https://github.com/${REPO}/releases`;
export const LATEST_API = `https://api.github.com/repos/${REPO}/releases/latest`;
