# Changelog

All notable changes to this project are documented here.
本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布] / [Unreleased]

### Added / 新增
- 新增「图片」题型：可插入图片并调整**宽度与对齐**；上传时在本机自动压缩，**仅存浏览器缓存（localStorage）**，不上传、不增加服务器压力；打印 / 导出 PDF 时正常显示。
  New "Image" block: insert images with adjustable **width and alignment**; compressed locally on upload and stored **only in the browser (localStorage)** — no server load; renders in print / PDF.
- **解答题每题可插入图片**（题干图）：在每题作答区上方显示，可调图片宽度。
  **Per-question images in free-response blocks**: a figure shown above each answer area, with adjustable width.
- **选择题支持任意选项数（2–60）**：字母按 `A…Z → AA, AB, …` 续排；选项过多时自动换行，并按纸张宽度与字号限制列数，**绝不溢出**。
  **Choice questions support any option count (2–60)**: labels continue `A…Z → AA, AB, …`; when there are too many options they wrap automatically, and the column count is limited by paper width and font size so nothing overflows.
- 考号填涂区：**中括号内直接显示数字**（`[0] [1] …`），顶部「考 号」跨列标题 + 手写行，一排数字即可。
  Exam-number grid: **digits are shown inside the brackets** (`[0] [1] …`), with a spanning "考号" header and a write-in row.

### Fixed / 修复
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
