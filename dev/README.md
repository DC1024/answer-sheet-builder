# dev/ —— 开发辅助脚本

这些脚本**只用于开发和验证**，不参与构建，也不会进任何 Docker 镜像。

## gen_omr_fixtures.cjs

重新生成 `scanner/tests/fixtures/` 里的测试素材。

**为什么要有它**：扫描识别服务的测试素材必须是「真实制卡端渲染出来的答题卡」，
不能手搓。否则测试能过、真机对不上。这个脚本用无头 Chromium 打开真实的 `app.html`，
直接调用 `exportOmrTemplate()` 拿模板，再用 CSS 把指定选项涂成深色 / 浅灰，逐份截图导出 PNG。

```bash
# 1. 仓库根目录起个静态服务
python -m http.server 8080

# 2. 另开终端（需要一个可用的 Chromium）
npm i playwright-core
node dev/gen_omr_fixtures.cjs

# 自定义位置：
BASE=http://127.0.0.1:8080 CHROME=/path/to/chrome node dev/gen_omr_fixtures.cjs
```

产出（覆盖写入）：

| 文件 | 内容 |
| --- | --- |
| `template.json` | 阅卷模板（`asb-omr/1`） |
| `s01.png` ~ `s06.png` | 6 份已模拟涂卡的答题卡，约 383dpi |
| `expected.json` | 每份卷子的预期答案（第 3 题留空、第 8 题浅涂） |

素材里刻意埋了两个边界情况：**第 3 题未涂**（应判 `blank`）、**第 8 题用中灰浅涂**（应判 `faint`）。
这两条是判定逻辑最容易退化的地方。

## 怎么验证

```bash
# 离线自检（不需要服务，不需要网络）
cd scanner && python tests/test_omr.py

# 服务级集成（需要先跑起来服务）
cd scanner && pip install requests
docker compose up -d
python tests/e2e_service.py                          # 默认 127.0.0.1:8081
BASE=http://192.168.1.10:8081 python tests/e2e_service.py
```

## 前端验证脚本（无头 Chromium + 真页面）

单元测试测不到「老师在页面上点出来的结果」。下面这些脚本用 `playwright-core` 打开**真实的页面**
（不是 mock），逐条断言肉眼能看见的东西。

```bash
# 依赖：playwright-core + 一个 Chromium（默认找 %LOCALAPPDATA%\ms-playwright\chromium-1234\）
# 用 CHROME= 指定别的可执行文件
NODE_PATH=<node_modules> node dev/verify_subjective.cjs
```

| 脚本 | 验什么 | 前置 |
| --- | --- | --- |
| `static_server.cjs` | 给制卡端用的只读静态服务（ES Module 必须走 http 才加载得起来） | — |
| `verify_settings.cjs` | 制卡端「⚙ 设置 / 检查更新」：三种剧本（有新版本 / 最新 / 断网）、开关持久化、**打印时弹窗不印到卷子上** | 无（自己起服务；GitHub API 被路由拦截成假的） |
| `verify_writebox.cjs` | 手写框（`writebox`）渲染 → 导出模板：6 道 `write` 题、坐标齐全 | 静态服务（`BASE=`，默认 8080） |
| `check_writebox_template.py` | **扫描端 `decode_write` 链路**（`verify_writebox.cjs` 的第二步）：在 write 坐标上"手写"一遍，看认不认得出 | 先跑 `verify_writebox.cjs` |
| `verify_subjective.cjs` | 制卡端「人工阅卷」配置 → 导出模板：勾过的题才带 `region` / `points` / `subs`，坐标单调不串位，解答题区域是「整题一块」 | 静态服务（`BASE=`，默认 8123） |
| `check_subjective_template.py` | **扫描端解析同一份模板**（`verify_subjective.cjs` 的第二步） | 先跑 `verify_subjective.cjs` |
| `verify_subjective_ui.cjs` | **阅卷工作台主观题打分 UI**：三列表头、两种给分模式、裁剪/整页切换、实时合计、保存后重开还在、未打分不计入总分（43 条） | 先跑 `seed_subjective_ui.py` |

### 跨端脚本怎么跑（两步）

凡是要「node 调 Python」的验证，都拆成两个脚本：

```bash
# writebox：制卡端导出 → 扫描端识别
NODE_PATH=<node_modules> BASE=http://127.0.0.1:8123 node dev/verify_writebox.cjs
scanner/.venv/Scripts/python.exe dev/check_writebox_template.py

# 主观题：制卡端导出 → 扫描端解析
NODE_PATH=<node_modules> node dev/verify_subjective.cjs
scanner/.venv/Scripts/python.exe dev/check_subjective_template.py

# 阅卷工作台 UI：先起真服务（挂住不退出），再用真浏览器点
scanner/.venv/Scripts/python.exe dev/seed_subjective_ui.py
NODE_PATH=<node_modules> node dev/verify_subjective_ui.cjs
```

**为什么必须拆**：本机沙箱里 **node 起不了任何子进程**（`execFileSync` 连 `cmd.exe` 都
`EBUSY`），所以「node 脚本内部顺便把 Python 服务/脚本拉起来」这种写法在这里只会得到一个
**看起来跑了、其实没跑**的假绿。拆成两个脚本、由外面的 shell 串起来，每一步都真的执行了，
失败也看得见。

> `dev/verify_scanner_settings.cjs`（扫描端设置卡片）同样需要 node 起 Python 服务，
> 在沙箱里跑不通 —— 那**不是**被测代码的问题。
