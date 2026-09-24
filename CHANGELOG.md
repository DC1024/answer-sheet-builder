# Changelog

All notable changes to this project are documented here.
本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布] / [Unreleased]

### Added / 新增
- **解答题作答区可直接拖动调高度**：预览区每题作答区的下边缘有拖动把手（悬停出现蓝条），按住上下拖即**实时**改变高度（把手同步显示当前 mm 数，40–400mm 自动夹取）；松手才写入配置并记为一个撤销点，属性面板数字同步更新。拖动过程不重渲染（重渲染会把把手从指针下抽走），打印 / 导出 PDF 时把手自动隐藏。
  **Drag the bottom edge of a free-response answer area in the preview** to resize it live — the grip shows the current mm value while dragging (clamped 40–400mm); the value is committed on release as one undo step and the properties panel stays in sync. The grip is hidden in print / PDF.
- **撤销 / 重做**：快照式历史（最多 100 步），连续输入会按 0.7s 时间窗合并为一步；工具栏 `↶ 撤销 / ↷ 重做`（无历史时置灰），快捷键 **Ctrl+Z / Ctrl+Y（或 Ctrl+Shift+Z）**。
  **Undo / redo**: snapshot history (up to 100 steps) with a 0.7s coalescing window for continuous typing; toolbar buttons grey out when unavailable; **Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z)**.
- **复制 / 剪切 / 粘贴**：**Ctrl+C / Ctrl+X / Ctrl+V** 复制选定模块到应用内剪贴板并插到其后；剪贴板里是模块 JSON 时也能直接粘贴；选中「图片」模块时 **Ctrl+V 可直接粘贴剪贴板中的图片**（本机压缩后存储）。文本框内一律让给浏览器原生行为，不劫持。
  **Copy / cut / paste** with **Ctrl+C / Ctrl+X / Ctrl+V**; a module JSON on the clipboard also pastes; with an Image block selected, **Ctrl+V pastes an image from the clipboard** (compressed locally). Keystrokes inside text fields are left to the browser.
- 选择题新增**「行间距(mm)」**：填涂与手写（横线）两种样式都生效 —— 手写样式尤其需要留出书写高度。
  New **row spacing (mm)** for choice questions, effective in both bubble and handwritten styles.
- 填空题**分层自动编号**：小题 `（1）（2）` → 小小题 `①②` → 再深 `a) b)`，各层一眼可区分；留空即自动编号、填写则手写覆盖。旧模板里那批硬编码的 `（1）（1）（1）` 会自动重算。
  **Layered auto-numbering** for fill-in-blank: sub `(1)(2)` → sub-sub `①②` → deeper `a) b)`; blank means auto, typed text overrides. Legacy hard-coded `(1)(1)(1)` is re-derived.
- 属性面板提示：结构面板新增快捷键说明条；操作后有「已复制 / 已剪切 / 已撤销」轻提示。
  Shortcut hint bar in the structure panel and toasts for copy / cut / undo.
- **四角定位点**：支持「方块 / 三角」两种样式，可调边长（2–10mm）。每一面（A3 正反面、A4 各页）**只有含题目内容时才自动加上四角定位点**，空白面不加；打印时强制输出底色（`print-color-adjust: exact`）。
  **Corner registration marks** in **square / triangle** styles with adjustable size (2–10mm). Every face that **contains content** automatically gets four corner marks — blank faces get none; rendered in print via `print-color-adjust: exact`.
- 新增「图片」题型：可插入图片并调整**宽度与对齐**；上传时在本机自动压缩，**仅存浏览器缓存（localStorage）**，不上传、不增加服务器压力；打印 / 导出 PDF 时正常显示。
  New "Image" block: insert images with adjustable **width and alignment**; compressed locally on upload and stored **only in the browser (localStorage)** — no server load; renders in print / PDF.
- **解答题每题可插入图片**（题干图）：在每题作答区上方显示，可调图片宽度。
  **Per-question images in free-response blocks**: a figure shown above each answer area, with adjustable width.
- **选择题支持任意选项数（2–60）**：字母按 `A…Z → AA, AB, …` 续排。
  **Choice questions support any option count (2–60)**: labels continue `A…Z → AA, AB, …`.
- 考号填涂区：**中括号内直接显示数字**（`[0] [1] …`），顶部「考 号」跨列标题 + 手写行，一排数字即可；位数上限提升至 20。
  Exam-number grid: **digits are shown inside the brackets** (`[0] [1] …`), spanning header + write-in row; digit cap raised to 20.
- **选择题列数改为「渲染时实测」**：把单题渲染到离屏容器量真实宽度后决定列数，字号、字体度量、多字符字母都自动算准，不再依赖手写常量。
  **Choice column count is now measured at render time** instead of estimated from hard-coded constants.

### Changed / 变更
- **分页改为严格「面 → 栏」顺序填充**：先把第一页第一面第一栏填满，再第二栏；第一面满了才用第二面，然后是第二页第一面、第二面……不再挑「最矮栏」做均衡（均衡会让内容左右跳跃，读起来是乱序的）。
  **Pagination now fills strictly in face → column order** instead of balancing column heights.
- **填空题改为「行内流式」**：一行没用完就继续把后面的小题放在同一行，排满才换行；每个小题包成原子块，换行时整块下移，不会把「（2）+ 空格」拆开。
  **Fill-in-blank now flows inline**: sub-questions keep filling the same line until it is full; each sub-item is atomic so it never splits across lines.
- **考号填涂区宽度加上限**：默认不超过**页面宽度的 1/4**（可在属性面板调 10–60%），把宽度让给右侧手写栏。上限内会把方框撑到尽量大（3–5mm）——唯一例外是上限内连 **3mm 可填涂下限**都放不下时（位数很多 / 纸张较小），此时自动放宽到刚好放得下，且永不超出纸张。实测：A3 16 位 87.6→**74.5mm**（25% 页宽），A4 16 位 107.3→**63.9mm**，A4 20 位 133.0→**78.8mm**。
  **The exam-number grid is now width-capped** at **1/4 of the page width** by default (adjustable 10–60%). Bubbles are still pushed to 3–5mm inside the cap; the only exception is when even the **3mm fillable minimum** cannot fit — then the cap is relaxed just enough, never overflowing the paper. Measured: A3 16 digits 87.6→**74.5mm** (25% of page width), A4 16 digits 107.3→**63.9mm**, A4 20 digits 133.0→**78.8mm**.

### Fixed / 修复
- **选择题「行间距」不作用于标题与第一行之间**：`行间距` 只驱动了 grid 的 `row-gap`，而 `row-gap` **只作用在行与行之间**，第一行之前不会自动加 —— 于是「一、选择题」标题到第一题的间距恒定在 **2.12mm**，与设定值无关（设 16mm 时行→行 17.12mm、标题→第一行却只有 2.12mm，差 15.00mm）。现在给 `.sc-grid` 补上 `padding-top: max(0px, calc(var(--hg) - 4px))`（用 padding 而非 margin 以避免与 `.blk-title` 外边距折叠，`-4px` 抵消 `.scq` 自身 2px 上下内边距）。实测：16mm → 17.12 / 17.12，8mm → 9.09 / 9.09，4mm → 5.07 / 5.07，1mm → 2.12 / 2.06；填涂样式与「每行 4 题」同样一致，**差值 0.00mm**。行间距 8→16mm 增量 8.03mm、4→8mm 增量 4.02mm，零溢出。
  **Choice row spacing now applies above the first row too.** The setting only drove the grid `row-gap`, which acts *between* rows and never before the first one — so the title→first-row gap stayed fixed at **2.12mm** (16mm setting measured 17.12mm row-to-row vs 2.12mm title-to-first-row). `.sc-grid` now gets `padding-top: max(0px, calc(var(--hg) - 4px))`. Measured: 16mm → 17.12 / 17.12, 8mm → 9.09 / 9.09, 4mm → 5.07 / 5.07, 1mm → 2.12 / 2.06 — **0.00mm difference**, same in bubble style and with 4 questions per row.
- **填空题「行间距」不均匀**：`行间距` 同时被用作折行后的 `line-height` **和** 大题之间的 `margin-bottom`，于是「题与题之间 = 行距 × 2」—— 设 16mm 实测题内 16mm、题间 **32.1mm**（6mm → 12.1mm，24mm → 48.2mm，全部正好翻倍）。现在 `.fill-q` 之间不再额外加外边距，行框直接相接：**题间行距 = 题内折行行距 = 设定值**，实测 6/10/16/24mm 与字号 14/18px 全部一致（16mm → 16.06 / 16.06）。行距仍带 1.4 倍字号下限，防止上下行重叠。
  **Uneven row spacing in fill-in-the-blank**: the spacing value was used both as the wrapped-line `line-height` **and** the `margin-bottom` between questions, so the gap between questions was exactly **2×** the setting (16mm measured 16mm inside a question but 32.1mm between questions; 6→12.1, 24→48.2). The extra margin is gone — line boxes now butt together, so **question-to-question pitch equals wrapped-line pitch equals the setting** (verified at 6/10/16/24mm and 14/18px).
- **定位点不再压住内容**：定位点此前固定内缩 4mm、而内容区从 7mm 就开始，必然与区块边框 / 横线重叠。现在页内边距由「定位点占用的页边距带」反推（内缩 + 边长 + 1mm 空隙），定位点永远落在页边距内；实测与内容最小间距 1.01mm、重叠面积 0mm²（4mm / 8mm 边长均成立）。
  **Corner marks no longer overlap content.** They used to sit at a fixed 4mm inset while content started at 7mm, so they inevitably collided with block borders. Page padding is now derived from the band the marks occupy (inset + size + 1mm clearance); measured clearance is 1.01mm with 0mm² overlap (verified at 4mm and 8mm).
- **考号填涂格可填涂性 / 可读性**：不再用 `12/位数` 硬缩字号，改为**由宽度反推方框边长**（3–5mm），相邻间距按格宽自适应（宽格留大间距、紧格贴紧排）。实测：A3 16 位 3.25→**3.67mm**（并受 1/4 页宽上限约束）、8 位顶到 5mm 上限，所有组合均 ≥3mm、零溢出。位数较多时会先压缩右侧手写栏，仍不够才缩小方框。
  **Fillability / legibility of the exam-number grid**: the old `12/digits` font shrink is gone. The bubble edge length is now derived from the available width (3–5mm) and the gap adapts to the cell width. Measured: A3 16 digits 3.25→**3.67mm** (under the 1/4-page-width cap), 8 digits hits the 5mm ceiling; every combination stays ≥3mm with zero overflow.
- **属性面板排版**：`每行题数（上限，放不下时自动减少列数以保证每题完整）` 这类长标签会把一行撑成三行，导致同行两个输入框一高一低错位。标签统一精简为一行、说明移入 `hint`，并让两列输入框底部对齐；实测全部标签单行、输入框底部差 0px。
  **Properties panel layout**: long labels used to wrap to three lines and knock the two inputs in a row out of alignment. Labels are now single-line with the explanation moved to a hint, and inputs in a row are bottom-aligned (measured: all labels single-line, 0px bottom offset).
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
