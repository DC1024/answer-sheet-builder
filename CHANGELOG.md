# Changelog

All notable changes to this project are documented here.
本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-09-24

首个正式版本。The first stable release.

### Added / 新增
- 模块化题型：选择题、填空题、解答题、考生信息栏、自定义编辑区，支持添加 / 复制 / 删除 / 拖拽排序。
  Modular question types (choice, fill-in-blank, free-response, student info, custom block) with add / duplicate / delete / drag-reorder.
- 选择题两种作答样式：中括号 `[A]` 填涂 与 横线手写；每行题数按纸张宽度自动适配。
  Choice questions in bracketed-bubble or handwritten style; columns auto-fit paper width.
- 填空题多级小题（如 11（1）、11（2）①/②），顶层首个小题紧跟题号内联、其余换行；空格长度与行间距可调。
  Nested fill-in-blank items; first sub-item inline, others wrapped; adjustable blank length and row spacing.
- 解答题作答区支持「空白」与「横线」两种样式，横线间距、作答区高度可调。
  Free-response areas in blank or ruled style; adjustable line gap and height.
- 考号填涂区（0–9 数字气泡网格），启用后手写栏自动排布于其右侧。
  Exam-number bubble grid; handwritten fields auto-arranged to its right.
- 固定纸张分页：A3（每面双栏）/ A4，竖版 / 横版；纸张尺寸固定，内容按面顺序填充。
  Fixed-size pagination for A3 (two columns per face) / A4, portrait / landscape.
- 每个题型区块统一黑色边框。
  Uniform black border on every question block.
- 通用样式：每个模块可独立设置字号与对齐方式。
  Per-module font size and alignment.
- 打印 / 导出 PDF，支持双面长边翻转；JSON 模板导入 / 导出；localStorage 保存 / 载入。
  Print / export PDF with duplex; JSON template import / export; localStorage save / load.
- Docker 部署（`Dockerfile` + `docker-compose.yml`），纯静态无需后端。
  Docker deployment; pure static, no backend.

[1.0.0]: https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.0
