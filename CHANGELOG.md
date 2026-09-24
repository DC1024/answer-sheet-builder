# Changelog

All notable changes to this project are documented here.
本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布] / [Unreleased]

### Added / 新增
- **四角定位点**：支持「方块 / 三角」两种样式，可调边长（2–10mm）。每一面（A3 正反面、A4 各页）**只有含题目内容时才自动加上四角定位点**，空白面不加；打印时强制输出底色（`print-color-adjust: exact`）。
  **Corner registration marks** in **square / triangle** styles with adjustable size (2–10mm). Every face that **contains content** automatically gets four corner marks — blank faces get none; rendered in print via `print-color-adjust: exact`.
- 新增「图片」题型：可插入图片并调整**宽度与对齐**；上传时在本机自动压缩，**仅存浏览器缓存（localStorage）**，不上传、不增加服务器压力；打印 / 导出 PDF 时正常显示。
  New "Image" block: insert images with adjustable **width and alignment**; compressed locally on upload and stored **only in the browser (localStorage)** — no server load; renders in print / PDF.
- **解答题每题可插入图片**（题干图）：在每题作答区上方显示，可调图片宽度。
  **Per-question images in free-response blocks**: a figure shown above each answer area, with adjustable width.
- **选择题支持任意选项数（2–60）**：字母按 `A…Z → AA, AB, …` 续排。
  **Choice questions support any option count (2–60)**: labels continue `A…Z → AA, AB, …`.
- 考号填涂区：**中括号内直接显示数字**（`[0] [1] …`），顶部「考 号」跨列标题 + 手写行，一排数字即可；位数上限提升至 20（超过 12 位整表按 `em` 等比缩小）。
  Exam-number grid: **digits are shown inside the brackets** (`[0] [1] …`), spanning header + write-in row; digit cap raised to 20 (scales down proportionally beyond 12).
- **选择题列数改为「渲染时实测」**：把单题渲染到离屏容器量真实宽度后决定列数，字号、字体度量、多字符字母都自动算准，不再依赖手写常量。
  **Choice column count is now measured at render time** instead of estimated from hard-coded constants.

### Fixed / 修复
- 修复选择题换行逻辑：改为**保证「题号 + 全部选项」在单行内完整排下**，排不下的整题换到下一行 —— 不再出现「某题最后一个选项被挤到第二行」。（A3 双栏 + 4 选项 + 14px 实测由「5 列全部折行」修正为「4 列全部整行」。）
  Fixed choice-question wrapping: a question **always fits entirely on one line**; if it doesn't fit, the whole question moves to the next row — no more "last option squeezed onto line 2". (Verified on A3 two-column, 4 options, 14px: was 5 columns with every question wrapped, now 4 columns with none wrapped.)
- 修复**选择题「字号 / 对齐」完全失效**（旧版把作答样式存在 `config.style`，与通用样式对象同名冲突，严格模式下抛 `TypeError`）：作答样式改用 `config.mode`，旧模板自动迁移。
  Fixed **font size / alignment being completely dead on choice blocks** (the answer style was stored in `config.style`, colliding with the common-style object and throwing a `TypeError` in strict mode): the answer style now lives in `config.mode`, with automatic migration of old templates.
- 修复「通用样式」中**调整字号无反应**：子元素改用 `em`，随 `.blk` 字号整体缩放。
  Fixed **font-size having no effect**: children now use `em` and scale with the block's font size.
- 修复**考生信息栏对齐（左 / 中 / 右）无反应**：对齐同时驱动 flex 容器的 `justify/align`。
  Fixed **student-info alignment (left / center / right) having no effect**: alignment now drives the flex containers too.
- 修复填空题**小题与小题之间（如 11（1）与（2）之间）行间距无效**：小题换行后按「行间距」拉开。
  Fixed **row spacing between sub-questions (e.g. 11(1) vs (2))** having no effect: wrapped sub-questions now honor the row-spacing value.
- 修复填空题**小题内换行后（第一行与第二行）行距不跟随设置**：`line-height` 改为跟随「行间距」。
  Fixed the **line spacing inside a sub-question (between wrapped lines)** not following the setting: `line-height` now tracks the row-spacing value.

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
