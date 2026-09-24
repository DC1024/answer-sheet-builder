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
