# Changelog

All notable changes to this project are documented here.
本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

_（暂无）_

## [1.1.0] - 2026-09-26

### Added / 新增
- **扫描端：人工修正（改机器读错的答案）**。阅卷工作台逐题复核里，每题直接改答案（机器原读标红显示），改完即落库，并**穿透进判分、班级分布统计、CSV 导出、成绩单**；原机器读数（`machine`）始终保留，供误判率统计使用。卷面考号也能改（`/api/fix/sid`），机器读错考号 = 整份卷子归错人，改完即时生效。重传扫描件时人工修正按考号搬回（`save_students(keep_manual)`），不会白改。
  **Scanner: manual correction of machine misreads.** In the gradebook review modal each question's answer is directly editable (the machine's original read is shown in red); a correction is persisted and propagates into scoring, class distribution stats, CSV export and the score sheet, while the original machine reading (`machine`) is always retained for misjudgment-rate accounting. The scanned candidate number is also editable (`/api/fix/sid`); a misread ID misattributes the whole paper and the fix applies immediately. Re-uploading scans carries corrections back by ID (`save_students(keep_manual)`), so manual work is never lost.
- **扫描端：识别方案标识 + 按方案误判率**。每道题标注用的是哪套识别方案 —— **结构特征规则**（纯 OpenCV，选择题填涂圈判定，零模型）还是 **CNN**（手写 A–D 交叉验证，装好 torch 权重后启用），一份卷子两套都用时显示「混合」。④汇总统计新增「识别方案与误判率」面板，按方案统计「被老师亲手改掉的比例」（`engine_accuracy`），并**原样展示有偏样本提醒**（只有老师看过并动手改的题才进统计，不等于全量准确率）。批量接口 / 单张扫描 / health 都带上 `engine` 口径与逐题 `by`。
  **Scanner: recognition-scheme label + per-scheme misjudgment rate.** Every question is tagged with the scheme that read it — **structural-rule** (pure OpenCV bubble detection, zero model) or **CNN** (handwritten A–D cross-check, enabled once torch weights are present); a paper using both shows "mixed". A new "识别方案与误判率" panel in ④ stats reports, per scheme, the share of questions the teacher manually corrected (`engine_accuracy`), and shows the biased-sample caveat verbatim (only questions the teacher actually reviewed enter the count, so it is not full accuracy). The batch / single-scan / health endpoints all carry the `engine` verdict and per-question `by`.
- 新增离线测试 `scanner/tests/test_fixes.py`：钉死人工修正的规整 / 生效 / 落库 / 穿透统计与导出、重传不丢、考号改名拒绝、只读账号权限，以及按方案误判率的分桶（rule / cnn / both / 无来源）与有偏样本口径。
  New offline suite `scanner/tests/test_fixes.py` locks in manual-correction normalization, application, persistence, propagation into stats/export, keep-on-rescan, sid-rename rejection, viewer permissions, and per-scheme misjudgment-rate bucketing (rule / cnn / both / unknown) with the biased-sample semantics.

### Changed / 变更
- 库结构升级到 `SCHEMA_VERSION = 3`：学生表新增 `fixes`（按题号存的人工修正，JSON 键统一成 int 避免静默失效）、`fixedQnos`（已修正题号清单）、`machine_*` 原读字段。
  Schema bumped to `SCHEMA_VERSION = 3`: students gain `fixes` (per-question manual corrections, JSON keys normalized to int to avoid silent mismatch), `fixedQnos` (corrected question list) and `machine_*` original-read fields.

## [1.0.3] - 2026-09-26

### Added / 新增
- **Windows 免安装版：制卡端 + 扫描端**。Release 里多了两个 zip —— `答题卡制作器`（制卡端）与 `答题卡扫描服务`（扫描端），解压后双击 exe 就用，**不需要装 Python、不需要 Docker**，数据库和校对图落在 `%LOCALAPPDATA%\asb-scanner\data`。
  制卡端是纯静态站点，脚本用 ES Module 组织，而浏览器**不允许在 `file://` 下加载模块**（双击 `app.html` 只会白屏）——所以启动器自带一个只监听 `127.0.0.1` 的本地静态服务并自动打开浏览器。扫描端则是把 Flask + OpenCV（+ 可选的手写 CNN）打成 onedir，启动器在 **import 之前**先把数据目录钉死（否则冻结成 exe 后 `__file__` 落在 PyInstaller 的临时解包目录，等于每次启动都清空），再用 waitress 起服务；端口被占用会自动往后找。
  **Windows portable builds for both ends.** The release now ships two zips — the sheet builder and the scanner — that run by double-clicking an exe, **no Python and no Docker required**, with the database and proof overlays under `%LOCALAPPDATA%\asb-scanner\data`. The builder is a static ES-module site, and browsers refuse to load modules over `file://` (double-clicking the html just gives a blank page), so its launcher bundles a loopback-only static server and opens the browser. The scanner is packaged as an onedir app; the launcher pins the data directory **before** importing the app (a frozen `__file__` points into PyInstaller's temp extraction dir, so the default would wipe state on every start) and serves through waitress, walking to the next port when 8081 is taken.
- **Windows 编译发布流水线**。新增 `.github/workflows/release-windows.yml`：推 `v*` 标签即在 `windows-latest` 上编译两个产物并**自动挂到对应的 GitHub Release**（也可手动触发，只出 Artifact 不发 Release）。打包逻辑全部落在仓库里的 `packaging/windows/build.ps1`（本地与 CI 同一套，PS 5.1 与 pwsh 7 都能跑），后面跟着 `ci_smoke.ps1` 把两个 exe **真起一遍**再验接口 —— PyInstaller 最常见的失败不是「打不出来」而是「打出来了但一跑就崩」（漏 hiddenimport / 漏数据文件），这一关专治它。
  **Windows build & release pipeline.** A new workflow builds both artifacts on `windows-latest` on `v*` tags and attaches them to the GitHub Release (manual runs only produce Artifacts). All packaging logic lives in `packaging/windows/build.ps1` so local and CI build identically, followed by `ci_smoke.ps1` which actually launches both exes and probes their HTTP endpoints — the classic PyInstaller failure is not "it won't build" but "it built and dies on launch" (missing hiddenimport / missing data file), which is exactly what this step catches.
- **手写 A-D 接入 CNN 分类器**。新增 `app/cnn_letter.py`（SmallCNN：4 层卷积 + 2 层全连接，输入 48×48 二值字形）与训练好的权重 `app/hwletter_cnn.pt`（9.7 MB，249 张真实学生手写样本，验证集 100%、全量复测 99.2%）。识别链路里 `decode_write` 改为 **CNN 一选 + OpenCV 交叉验证**：两者一致且 CNN 置信 ≥ 0.70 → 直接判；不一致 → 标 `review`；CNN 置信不足 → 按原逻辑标 `doubt`，都进「存疑」队列交给老师。真实手写整卷净准确率 **75.5% → 94.3%**，其中置信判定部分 99.4%（163/164）。torch 是**惰性 import**，没有 torch 或没有权重时整条手写识别优雅退回纯 OpenCV，服务照常启动、绝不因加载失败而崩。
  **CNN first-pass classifier for handwritten A–D.** New `app/cnn_letter.py` (a small CNN over 48×48 binary glyphs) with trained weights `app/hwletter_cnn.pt` (9.7 MB; 249 real student handwriting samples — 100% on the held-out split, 99.2% on a full re-test). `decode_write` now runs **CNN as the primary classifier with OpenCV as a cross-check**: agreement above 0.70 confidence is accepted outright, disagreement is flagged `review`, low confidence is flagged `doubt` — both land in the teacher's review queue. Net accuracy on real handwritten sheets went **75.5% → 94.3%**, 99.4% (163/164) on the auto-decided subset. torch is imported lazily, so a deployment without torch or without the weights degrades cleanly to pure OpenCV instead of failing to boot.
- 扫描端新增环境变量 `ASB_DATA`（数据目录，容器里仍是 `/srv/data`）与 `ASB_CNN_MODEL`（权重路径；指到一个不存在的路径即可显式关掉 CNN、省内存），新增 `app/hwletter_cnn.pt` 随镜像走。
  New scanner env vars: `ASB_DATA` (data dir) and `ASB_CNN_MODEL` (+ the weights now ship inside the image).

- **扫描服务：真实手写精度基准工具** `tools/bench_real_handwrite.py`。拿一批真实学生手写扫描件 + 对应阅卷模板 + 真值答案，跑出可复现的精度结论：净准确率、**混淆矩阵**（一眼看出哪个字母在往哪个字母上塌）、flag 分布，以及**「自动阅卷精度 vs 人工复核量」权衡曲线**（调 `DOUBT_CONF` 的依据）。支持 `--fail-under` 卡阈值用于 CI。改动手写识别后换任意一批手写卷都能复跑 —— 印刷体基准测不出真实笔迹上的洞收不拢口 / 断笔 / 框线问题。
  **Scanner: real-handwriting accuracy benchmark** (`tools/bench_real_handwrite.py`) — point it at a folder of real scanned sheets plus their template and ground truth to get a reproducible accuracy report: net accuracy, a **confusion matrix** (shows at a glance which letter is collapsing into which), flag distribution, and an **auto-grading accuracy vs. manual-review load** trade-off curve for tuning `DOUBT_CONF`. `--fail-under` turns it into a CI gate. Re-runnable on any new batch of handwriting — printed-fixture benchmarks cannot catch unclosed loops, pen lifts or box frames.
- **扫描服务：手写字母结构分类（半自动）**。`app/hwletter.py` 纯 OpenCV 特征分类手写/印刷 **A/B/C/D**：连通域提字形 → 洞数量/位置 + 轮廓顶底宽打分，大小写同收。模板题目加可选 `write` 作答框（`x/y/w/h` mm）即启用，识别时对该题走结构分类，新增 `flag: doubt/multi`（置信不足或双字母 → 进复核）。设计原则「宁可存疑、不可硬猜」。基准：real30 印刷体 900 样本 100% 识别 0 误判；合成工整手写整卷给出答案全对、不确定进复核。真实手写精度待真实笔迹素材。
  **Scanner: handwritten A-D structural classifier (semi-auto)** — pure-OpenCV feature classification (blob/contour features, upper+lower case). An optional `write` box per question routes recognition through it, with new `doubt`/`multi` flags feeding review. Design rule: never guess wrong — doubt goes to the teacher. Benchmarks: 900 printed samples 100% / 0 misreads; synthetic neat handwriting reads correctly when it answers the question, and defers otherwise. Real-handwriting accuracy awaits real-ink samples.
- **扫描服务：真实扫描件回归基准（real30）**。30 张真实答题卡扫描件入库（`tests/fixtures/real30/`），配套工具 `tools/make_template_from_real.py` 从扫描件**逆向生成阅卷模板**（自动找四角定位点 → 透视矫正 → 聚类测量 40 个选项框坐标 → 输出 `asb-omr/2` JSON），再用识别核心全量回验：30 张 × 10 题 = 300 个判定点全部与真值一致、零存疑。`tests/test_real30.py` 把这条基准钉死 —— 此后识别链路（矫正 / 采样 / 判定阈值）的任何改动都要过真实笔迹这一关，不再只靠合成图自证。
  **Scanner: real-scan regression baseline (real30)** — 30 real scanned answer sheets with a reverse-engineered OMR template (`tools/make_template_from_real.py`: corner marks → warp → bubble-grid clustering → `asb-omr/2` JSON). The full recognition chain scores 300/300 against ground truth with zero flags; `tests/test_real30.py` locks it in so any change to warp/sampling/decide must still pass real-ink data, not just synthetic fixtures.
- **扫描服务：成绩分析**。新增「⑦ 成绩分析」卡片：**每题难度系数**（P = 全班该题平均得分 ÷ 该题满分，规则感知、自动标注易/中/难并列出重点讲评题）、**成绩分布直方图**（复核分落桶，纯内联 CSS 绘制）、**学号段统计**（按班级或考号前 4/6/8 位分组：人数/平均/最高/最低/得分率）。数据全部来自工作台（含人工复核与评分规则），不另开接口。
  **Scanner: grade analysis** — a new card with per-question difficulty (P = class average ÷ full marks, rule-aware, tagged easy/medium/hard with focus suggestions), a score histogram (inline CSS, no external libs) and segment statistics (by class or SID prefix): count / avg / max / min / rate.
- **扫描服务：自定义评分规则**。④汇总统计新增「评分规则」编辑器，逐题（或批量）设置计分方式：**单选自定义分值**（答错可倒扣、未答不罚）、**多选漏选得部分分**（如漏选得一半，错选 0 或倒扣）、**按选对个数阶梯给分**（七选三典型 `对1个1分、对2个2分、对3个4分`）。规则随考试存盘（库结构 v2 加 `exams.rules`），工作台 / 复核 / 成绩导出全部联动重算；没配规则的题保持传统「答对 1 分」，老考试行为不变。多选题学生的实际涂选从识别时的逐选项墨迹推导，无需重新识别。
  **Scanner: custom scoring rules** — a per-question rule editor (with batch apply) supporting custom-points single choice (optional wrong-answer penalty), multi-choice partial credit (e.g. half points for missing selections) and ladder scoring by number of correct picks (e.g. 七选三 1/2/4). Rules persist with the exam (schema v2 `exams.rules`) and re-drive the gradebook, review flow and CSV export; questions without a rule keep the legacy 1-point behaviour. A student's multi-bubble selections are derived from per-option ink recorded at recognition time.
- **扫描服务：成绩单打印（一个学生一页）**。阅卷工作台一键「打印成绩单」：每位学生一页 A4（得分 / 原始分 / 逐题作答与判定 / 老师备注 / 师生签名栏），走浏览器打印即可存成 PDF，服务端零新依赖。
  **Scanner: printable per-student score sheets** — one A4 page per student (scores, per-question breakdown, teacher note, signature lines) via the browser's print-to-PDF; no new server dependencies.
- **扫描服务：批量上传（一个班一次传完）**。可以丢 **zip 压缩包**、**整个文件夹**（浏览器递归读取，保留目录结构）或一堆散图；按考号自动归组、多页自动合并成一份卷子，跨目录同考号会标为「疑似重复」。
  **Scanner: batch upload** — drop a **zip**, a **whole folder** (recursively read in the browser, directory structure preserved) or a pile of loose images; sheets are grouped by candidate number and multi-page sets merged into one paper, with cross-directory duplicates flagged.
- **扫描服务：学生名单匹配**。上传 `考号,姓名,班级` 的 CSV/TSV（Excel 导出的 GBK 也能读，表头别名宽松匹配），自动贴上姓名班级，并列出**待人工确认队列**：考号不在名单里、名单里有人没交卷、页序异常等；补录后点「重新套用」即可，**只改标注、不重新识别**。名单也可以直接放进 zip 里，服务自己找。
  **Scanner: roster matching** — upload a `id,name,class` CSV/TSV (GBK from Excel works, header aliases tolerated) to attach names and classes, with a **manual-confirmation queue** for unknown IDs, missing submissions and page-order anomalies. Fill-ins are re-applied without re-running recognition. The roster can also live inside the zip.
- **扫描服务：文件夹上传的 `paths` 约定**：浏览器选文件夹时每个文件带 `webkitRelativePath`，服务端据此还原目录结构 —— 同名文件靠目录区分，不会互相覆盖。
  **Scanner: `paths` contract for folder uploads** so identically-named files in different student folders stay distinct.
- **扫描服务：统计与导出默认只针对最近一次识别那一批**（原来会把历史结果全混在一起）。成绩 CSV 在有考号时自动补上**考号/姓名/班级**三列并考号排序；新增**名单对账 CSV**（考号/姓名/班级/页数/备注）用来核对谁没交。
  **Scanner: statistics and export now target only the most recent batch.** The score CSV gains **ID / name / class** columns (sorted by ID) when available, plus a new **roster reconciliation CSV**.
- **扫描服务：页序越界一定报错**。原先页序号越界会被静默夹到最后一页 —— 「多传了一页」会拿错的模板面采样，答案看着正常但是错的。现在该面明确报「超出模板范围」并进待确认队列，其余面的答案照常保留（一面出错不作废整份）。
  **Scanner: out-of-range page indices now error out** instead of being silently clamped to the last page — a sheet with an extra page would otherwise be sampled against the wrong template face and produce plausible-looking wrong answers.
- 扫描服务的接口可以独立使用了：`POST /api/roster`（单独导名单）、`POST /api/batch/rematch`（补录后重新套名单）、`GET /api/students`、`GET /api/roster.csv`。
  New scanner endpoints: `POST /api/roster`, `POST /api/batch/rematch`, `GET /api/students`, `GET /api/roster.csv`.
- 新增两份离线测试：`scanner/tests/test_batch.py`（路径解析 / 解包 / 归组 / 名单 / 页序）与 `scanner/tests/test_service.py`（Flask 测试客户端直打接口，**部署前**就能拦住接线问题）。
  Two new offline suites: `scanner/tests/test_batch.py` and `scanner/tests/test_service.py` (drives the API through Flask's test client, catching wiring bugs **before** deployment).
- **卷面考号：从答题卡上直接读考号，用不着二维码也用不着改名**。制卡端「考生信息栏」开启**考号填涂区**后，导出的阅卷模板会带上考号每一位格子的坐标（模板格式升级为 `asb-omr/2`，`asb-omr/1` 老模板继续可用）；扫描服务把考号从卷面上读回来，用它校正分组：
  - 文件名里**没有**考号（`IMG_0001.jpg`、`扫描件_20240925_1030.png`）→ **按卷面归组**，散着传的多页还会被并成一份；
  - 文件名里的考号与卷面**一致** → 互证；**不一致** → **保持原样不动**，两边都报出来让人确认（把卷子记错名字是不可逆的错）；
  - 卷面有 1~2 位没涂出来 → 名单里**有且只有**一个人符合时自动补全，否则留着缺位等人填；
  - 「文件名里的数字算不算考号」会分辨：`IMG_0001`／时间戳里的数字是序号不是考号，而目录名、
    `2026010234_1.png`、`张伟明-2026010234` 里的算（名单里有这个人也算）。
  名单对账 CSV 因此多了「考号来源」「说明」两列；界面每张考生卡上标出考号出处（卷面 / 文件名 / 互证 / ⚠ 冲突）。
  **Scanner reads the candidate number off the sheet itself** — no QR code per student, no renaming 50 files.
  Enabling the **ID fill-in block** in the sheet builder's candidate-info section makes the exported template carry
  every ID bubble's coordinates (template format `asb-omr/2`; `asb-omr/1` keeps working). Grouping is then corrected
  after recognition: a filename with no ID is overridden by the sheet, a mismatch is **never** silently acted on
  (both values are reported for confirmation), and a 1–2 digit hole is filled in only when the roster has exactly
  one candidate. `IMG_0001` / timestamp digits are recognised as serial numbers rather than IDs.
- **卷面考号读不准时会说自己读不准**。新增 3 份边界素材（漏涂 / 浅涂 / 一列涂两个）与逐位断言：
  漏涂位输出 `?` 占位并保持位数对齐（读出 `20?6010234`），浅涂位标 `faint`（中灰 ink 0.388），
  一列涂两个标 `doubt`（两格都是 0.827）。校对图会把考号选中的那一格也圈出来、圈旁标位数与数字。
  **The scanner reports uncertainty about the sheet-read ID** instead of guessing: three edge-case fixtures
  (blank / light / double-filled position) assert per-digit status, and the proof overlay circles the chosen ID cell.
- **名单能把考号洞补上、也能认出「只差一位」**：卷面上有位没涂出来时，若名单里只有一个人符合就自动补全；
  考号不在名单里且名单里**恰好有一个**只差一位的考号时，直接指出「是第几位、应该是几」
  （考号连号的学校会出现多个「只差一位」，那就只报「不在名单里」，不制造噪音）。
  **The roster repairs and corroborates IDs**: a single-digit hole is auto-filled when exactly one roster entry
  matches, and an ID that is off by exactly one digit from exactly one roster entry is pointed out by position.

- **扫描服务：登录与角色**。所有 `/api/*` **默认拒绝**（白名单只放 `/api/health` / `/api/login` /
  `/api/setup` / `/api/me`）；角色分**管理员 / 老师 / 只读**，判定的是**动作**不是数据
  （能不能改结果、能不能管用户）；**不内置任何默认口令**——库里一个用户都没有时，第一个打开页面的人
  走「创建管理员」，而不是拿 `admin/admin` 登录；口令只存 `pbkdf2_sha256` 散列（标准库实现，不引第三方依赖），
  会话存在**服务端 SQLite**，改口令 / 退出登录会即时失效、可吊销别处登录。新增账号管理（建账号 / 改角色 /
  重置口令 / 删除），**最后一个管理员既不能降级也不能删除**。
  **Scanner: login and roles.** Every `/api/*` is denied by default (only `/api/health` `/api/login`
  `/api/setup` `/api/me` are public); three roles (admin / teacher / viewer) gate *actions*, not data;
  no default password — the first visitor creates the admin when the user table is empty; passwords are
  `pbkdf2_sha256` hashes and sessions live server-side (revocable, killed on password change / logout).
- **扫描服务：结果持久化改为 SQLite（`data/asb.db`），考试为持久化单元**。去掉了原来的内存 `STATE`——
  **重启 / 刷新页面 / 换浏览器都不丢结果**，两个老师同时用也不会把对方的结果冲掉（并发串台这个老隐患没了）；
  多考试隔离、切换、删除，最近操作的考试会被记住。
  **Scanner: results now persist in SQLite, scoped by exam.** The in-memory `STATE` is gone — restart, refresh
  and concurrent teachers are all safe; multiple exams are isolated and switchable.
- **部署：`docker-compose` 健康检查改打 `/api/health`**。`/api/template` 现在要登录，沿用旧检查会把容器
  判成 unhealthy。
  **Deploy: the compose healthcheck now hits `/api/health`** — `/api/template` requires auth now, so the old
  probe would mark the container unhealthy.

- **阅卷工作台（在识别结果上人工复核 / 改分 / 标注）**。识别完不等于判分完 —— 机器判错的题、
  想给总分加减、想标「这卷子已复核 / 备注一句」都常发生。新增 `⑥ 阅卷工作台` 卡片：按考生逐张复核，
  每题可单独把判定覆盖成「对 / 错 / 恢复自动」，可填**手动总分覆盖**（不填则按自动判分），
  可勾**已复核**并写备注；工作台汇总「已复核人数 / 待复核 / 标记人数 / 平均分」。导出成绩 CSV 时
  勾「仅复核过的」会用 `复核分`（手动分优先、否则自动分）替代原来的自动分，表头也换成「复核分」。
  读写接口：`POST /api/grade`（写权限）、`GET /api/gradebook`（默认网关，只读也能看）。
  **Grading workbench — manual review / score adjustment / flagging on top of recognized results.**
  New `⑥ 阅卷工作台` card: per-student review, per-question override (correct / wrong / auto),
  optional manual total-score override, a "reviewed" flag and a note; the workbench summarizes
  reviewed / pending / flagged counts and the average. Exporting the score CSV with "graded only"
  emits a `复核分` column (manual score wins, else auto) instead of the raw auto score.

  **关键设计：阅卷是「覆盖层」，不改 schema、不冲掉识别结果。** 复核结论作为 `grading` 存进
  考生字典 `data` 的顶层键，走和 `answers` 完全相同的 `_fix_qkeys` 往返（题号 int↔字符串归一化），
  因此**重识别 / 重套名单 / 重启都不会丢复核结论** —— 因为 `bt.match()` 是就地改考生字典，
  会保留任意顶层键。钉在 `test_store.py` 的 K 节（存进去再读回来、重存仍在、未知考号报错）与
  `test_service.py` 的 M 节（改分 / 复核 / 只读 403 / 复核导出）。
  **Key design: grading is an overlay — no schema change, recognition results are untouched.**
  The review conclusion lives as a top-level `grading` key in the student `data` blob, round-tripping
  through the same `_fix_qkeys` as `answers`, so **re-matching / re-storing / restart never drop it**
  (`bt.match()` mutates the student dict in place and preserves arbitrary top-level keys). Pinned in
  `test_store.py` §K and `test_service.py` §M.

- **两端的「设置」页 + 检查更新**。制卡端工具栏右上角多了 `⚙ 设置`，扫描端多了 `⑧ 设置` 卡片，都做三件事：
  **自动检查更新可开可关**（默认开、6 小时内不重复查）、**可以手动点一下「检查更新」**（`?force=1` 绕过缓存）、
  **显示当前版本号**（来自服务端 / 版本模块的真身，不是前端写死的）。三种结局都说人话：
  🎉 有新版本（新版本号 + 可点的发行版地址 + 发行说明正文）/ 已是最新（附「3 小时前查的」）/
  **暂时查不到**（连不上 GitHub / 仓库还没发过 Release / 被限流，各给一句中文说明）。
  最要紧的一条设计是**「查不到」不是错误**：学校内网连不上 `api.github.com` 是常态，所以失败也当成一种
  **结果**返回（`ok:false` + `error`），**永不抛异常、永不 500**，前端也不弹红、不写 `console.error` ——
  否则内网部署第一天就会被一堆假警报淹没。
  两端查法不同：制卡端是**纯静态站点、没有后端**，直接浏览器 `fetch` 打 `api.github.com`
  （它带 `Access-Control-Allow-Origin: *`，跨域读得到）；扫描端由**服务端** `GET /api/update` 去查，
  结果落盘 `data/settings.json` 并按 6 小时缓存（**只缓存成功结果** —— 失败不缓存，下次打开还会再试）。
  开关也落在**服务端**而不是 `localStorage`：老师换台电脑打开，「这个服务要不要自动查」应该是同一个答案。
  只有**写权限**能改开关（只读账号开关是灰的，但版本号与「检查更新」照常可用，那只是查询）；
  写盘走临时文件 + `os.replace()`，断电不会留半个坏文件，文件被删/写坏则回落默认值。
  换源 / 内网镜像 / fork 出去自己发版，用 `ASB_UPDATE_API` 指一下即可，前端一行不用改。
  **Settings page + update check on both ends.** The builder's toolbar gained a `⚙ 设置` button and the
  scanner a `⑧ 设置` card; both let users **toggle the automatic check**, **trigger a manual one** (bypassing the
  cache) and **see the running version**. All three outcomes are spelled out: new version (number + clickable
  release link + notes) / already latest / **could not check** (offline, no releases yet, rate-limited — each
  with a human sentence). The governing rule is that **"cannot check" is not an error**: a school intranet
  can't reach `api.github.com` and that is normal, so failures come back as a *result* (`ok:false` + `error`),
  never raise, never 500, and the UI explains instead of going red. The two ends check differently — the
  builder is a **static site with no backend**, so the browser fetches `api.github.com` directly (it sends
  `Access-Control-Allow-Origin: *`); the scanner checks **server-side** via `GET /api/update`, caching the
  outcome in `data/settings.json` for 6 hours (**successes only**). The switch lives server-side rather than in
  `localStorage`, so it follows the service, not one machine. Only writers can flip it (viewers see it greyed
  out but can still check), writes go through a temp file + `os.replace()`, and a corrupt file falls back to
  defaults. `ASB_UPDATE_API` repoints the check at a mirror or fork.
- **打包产物自身的回归守卫**：`packaging/windows/ci_smoke.ps1` 把两个 exe **真起一遍**再打接口
  （制卡端验 `assets/js/app.js` 与 `style.css` 真的被供出来了、扫描端验 `/api/health` 的 `ok`、首页体积、
  `asb.db` 真的建出来了），并顺手 grep 启动日志里的「手写 CNN 已加载 / 加载失败」把它写进 CI 摘要 ——
  免安装版最容易出的问题不是「打不出来」而是「打出来了、双击就崩」，这一关专治它。
  前端侧另有两份无头 Chromium 回归：`dev/verify_settings.cjs`（制卡端，用 `ctx.route` 拦 GitHub 造三种剧本）
  与 `dev/verify_scanner_settings.cjs`（扫描端，起一个**假 GitHub API** 并把真服务用 `ASB_UPDATE_API` 指过去，
  走完整链路：前端 → `/api/update` → `app/update.py` → HTTP → 解析 → 落盘 → 回读）。
  **A regression guard for the artifacts themselves** — `ci_smoke.ps1` launches both exes and probes them
  (builder: `assets/js/app.js` and `style.css` actually served; scanner: `/api/health` `ok`, index size,
  `asb.db` created), grepping the launch log for the CNN load line into the CI summary. Plus two headless-Chromium
  suites: `dev/verify_settings.cjs` (builder, stubbing GitHub via `ctx.route`) and
  `dev/verify_scanner_settings.cjs` (scanner, with a **fake GitHub API** wired in through `ASB_UPDATE_API`,
  exercising the full chain).

### Changed / 变更
- **`/api/health` 新增 `cnn` 字段**：`{weights, torch, ready}` —— 手写 CNN 到底装进去没有。
  只做静态判断（权重文件在不在 + `torch` 能不能 `find_spec` 到），**不加载模型**（健康检查每几十秒
  被打一次，加载一次要 1~2 秒）。加这个是因为权重和 torch 都是可选件、缺了服务照样起得来，
  于是「服务活着」并不能证明「打包时装对了」—— 免安装版的冒烟测试就靠它与产物里的
  `hwletter_cnn.pt` 对账，对不上直接判打包失败。
  **`/api/health` now reports `cnn: {weights, torch, ready}`** — a cheap static check (weights present +
  `find_spec('torch')`) that does **not** load the model, since the health endpoint is polled every few
  seconds. Both pieces are optional and the service boots without them, so "it's alive" never proved
  "it was packaged correctly"; the portable smoke test now cross-checks this against the shipped
  `hwletter_cnn.pt` and fails the build on a mismatch.
- **扫描服务数据结构从「内存 STATE」迁到 SQLite**：所有接口改按 `exam_id` 读写；`/api/template` 现在需要登录
  （上传模板走写权限）。前端新增考试下拉、账号/角色 UI、`⑤ 账号管理`卡片（仅管理员可见）。
  **Scanner: in-memory STATE → SQLite; `/api/template` now requires login;** the UI gained an exam switcher,
  account/role management and an admin-only account card.

### Fixed / 修复
- **`test_real30.py` 不再写死张数**。31–60 这批手写版素材加进 `fixtures/real30/` 之后，
  `assert len(files) == 30` 就变成了一条**跟识别毫无关系**的假失败（多传几张扫描件必然失败）。
  现在以 `expected.json`（真值表）为准枚举素材：有真值的卷子必须都在、且全部与真值一致；
  「有素材、没真值」只提示不判失败 —— 但一定会把张数说出来，免得误以为「60 张全过了」其实只量了 59 张。
  **`test_real30.py` no longer hard-codes the sheet count.** Adding sheets 31–60 turned
  `assert len(files) == 30` into a false failure unrelated to recognition. The test now enumerates from
  `expected.json`: every ground-truthed sheet must be present and match exactly, while sheets still lacking
  ground truth are reported (never silently ignored) rather than failing the run.
- **打包脚本的中间目录清理不再可能拖垮一次成功的构建**。PyInstaller 的 `--workpath` 与 zip 的暂存目录
  改成**每次构建唯一**，于是这两处根本不需要「先删干净」；收尾清理降级为软失败（警告 + 继续）——
  它只是占点磁盘，绝不该把已经打好的产物判成失败。构建前清 `dist/release` 保持**硬失败**：
  那里的残留会以「合并」的方式混进产物（先带 CNN 构建、再去掉 CNN 重建，包里会仍然带着上一次的
  torch DLL，体积对不上、行为也不可预期），这点不能将就。删除被拒时的报错也换成了一句话说明 +
  该怎么做，而不是一坨看不出原因的 `NativeCommandError`。
  **Build-script cleanup can no longer fail an otherwise successful build.** PyInstaller's `--workpath`
  and the zip staging dir are now unique per run, so neither needs pre-cleaning; the finishing cleanup
  degrades to a warning. Clearing `dist/release` before assembling stays a **hard** failure, since leftovers
  there merge into the artifact (rebuild without the CNN and the package still carries the previous torch
  DLLs). A refused delete now reports a plain-language explanation instead of a wall of
  `NativeCommandError`.
- **免安装版扫描端：每一个响应都 500**。waitress 的 `ident` 会变成 HTTP 的 `Server:` 响应头，而响应头按
  latin-1 编码 —— 原本把中文的界面标题传给 `ident`，于是 `build_response_header` 里
  `UnicodeEncodeError: 'latin-1' codec can't encode ... ordinal not in range(256)`，
  **连 `/api/health` 都活不了**，表现是「进程在跑、端口在听、浏览器打不开任何页面」。
  改成 ASCII 的固定标识 `asb-scanner`。这个只在**打包成 exe** 后才显形（源码直跑时用的是另一条启动路径），
  正是 `ci_smoke.ps1` 把它拦下来的。
  **Scanner portable build: every response was a 500.** waitress turns `ident` into the `Server:` header, which
  is latin-1 encoded — passing the Chinese UI title made `build_response_header` raise
  `UnicodeEncodeError: 'latin-1' codec ... ordinal not in range(256)`, so **even `/api/health` died**: the process
  was up, the port was listening, and no page would load. Now a fixed ASCII `asb-scanner`. Only visible once
  packaged (source runs take a different path); `ci_smoke.ps1` caught it.
- **设置卡片的「检查更新」结果永远不显示**。结果区用内联 `style.display` 控制显隐，而卡片自己有一条
  `display:flex` 的样式规则 —— 它**盖过**了 UA 的 `[hidden]{display:none}`，于是元素「设了隐藏却还照样显示」；
  更糟的是脚本读回状态时读的是 `.style.display`，与实际渲染不一致。统一改成 `hidden` **属性** +
  一条显式的 `#setUpdBox[hidden]{display:none}` 兜底规则。同类坑在制卡端设置弹窗上也补了
  （`#setModal` 同样设了 `display:flex`），并加了 `@media print` 下强制隐藏。
  **The settings card's update result never appeared.** It was toggled with inline `style.display` while the
  card itself carries a `display:flex` rule, which **overrides** the UA's `[hidden]{display:none}` — the element
  was "hidden" yet still shown, and reading `.style.display` back disagreed with what was rendered. Switched to
  the `hidden` **property** plus an explicit `#setUpdBox[hidden]{display:none}` fallback, and applied the same
  fix to the builder's settings modal (also `display:flex`), with a `@media print` override.
- **手写 A-D 识别：真实笔迹上的精度修复（净准确率 42.9% → 62.9%）**。用 30 份真实学生手写卷（300 题）建基准后，暴露出两个**印刷体基准完全测不出来**的真实笔迹问题：① 作答框的印刷黑框常被断成多段（左竖 / 右竖 / 上下横 / 四角），每段外接矩形只占框宽 5%~9%，不满足原来「占满整框」的判据，于是全被当成手写的墨 —— 主字形旁多出一块第二大团墨直接触发 multi（Q5/Q10 实测 28/30 卷判 multi）。现在按「贴边 + 细长 / 贴边角块」剔除，且只作用于非主连通域，写得满框的大字不会被误删。② 真实手写 A/D 的洞**收不拢口**（起收笔有缝）：54% 的 A、54% 的 D 洞数 = 0，而原打分在无洞时无条件偏向 C，导致 153 个零洞样本 100% 判成 C（其中 98 个真值是 A/B/D）。现在无洞时改用形态判别：中部行带右侧无墨 → C 的右开口；底宽明显大于顶宽 → A 的两腿；右侧墨明显多于左侧 → D 的半圆弧。零洞准确率 36% → 69.3%（5-fold 交叉验证泛化 66.0%）。另外，同一字母被断笔切成上下两段时（次大域与主体包围盒实测重叠 78%）不再误判成「写了两个字母」。
  效果：净准确率 42.9% → 62.9%；**自信给出的答案准确率 79.3%**；D 的识别从 10/63 提升到 31/63。回归：印刷体 real30 仍 300/300 全对；合成形变样本上「自信地给错答案」从 170 个降到 10 个（率 0.236 → 0.014）—— 更守得住「宁可存疑、不可硬猜」。
  **Handwritten A-D recognition: real-ink accuracy fixes (42.9% → 62.9%).** Benchmarking 30 real student sheets (300 answers) exposed two failure modes that printed-fixture benchmarks cannot see: ① the printed frame around a write box usually breaks into several pieces (left/right verticals, top/bottom horizontals, corners), each spanning only 5–9% of the box width, so the old "spans the whole box" filter missed them all and they were counted as ink — the resulting second large blob tripped `multi` on 28/30 sheets for the rightmost questions. Pieces are now dropped when they hug an edge and are thin, or sit in a corner, and only for non-primary blobs so a large letter is never deleted. ② Real A/D loops often fail to close: 54% of A's and 54% of D's reported zero holes, and the scorer then unconditionally favoured C — all 153 zero-hole samples were read as C even though 98 of them were actually A/B/D. Zero-hole cases now fall back on shape: no ink on the mid-band's right side → C's opening; bottom much wider than top → A's splayed legs; right side markedly heavier than left → D's bowl. Zero-hole accuracy 36% → 69.3% (66.0% under 5-fold cross-validation). A letter broken into upper/lower halves by a pen lift is also no longer mistaken for two letters.
  Net accuracy 42.9% → 62.9%; **79.3% on answers given confidently**; D recall 10/63 → 31/63. Printed real30 still 300/300; on synthetically deformed samples, confidently-wrong answers dropped from 170 to 10 (0.236 → 0.014) — much closer to the "never guess, defer to review" rule.
- **手写 A-D 识别：第二轮优化（净准确率 62.9% → 76.6%）**。继续攻 D / B / A 之间的混淆，新增三个形态判据：① **中部 vs 两端墨量**：D 的半圆中部是空的（只剩左竖 + 右弧两条边），B 的双环在中部交汇成「腰」→ 中部墨明显更多（实测真值 D ≈ 0.91、真值 B ≈ 1.21，方向相反）；② **尖顶判 A**：A 的顶是两撇交汇的尖（顶宽 0.22），B 的上环顶是平的（0.47），差一倍多，原先只靠「底宽 − 顶宽」抓不到两腿张得不明显的 A；③ **竖长洞判 D**：洞窄时，竖长且贯穿的是 D 的半圆内腔（洞高/洞宽 ≈ 1.7），而 B 的环洞偏方（≈ 1.0）—— 这条**必须带顶宽护栏**：印刷体 B 的双环上下连通后同样是竖长洞，只凭洞形会把这类 B 全判成 D（实测 22 个误判全是 B→D），加上「顶不宽」条件后印刷体回到 0 误判，真实手写仍保留几乎全部收益。阈值取 5-fold 交叉验证选出的稳健值，零洞分支泛化 73.2%（全量拟合 ~77%）。
  效果：净准确率 62.9% → **76.6%**（最初 42.9%）；自动判的题从 149 增到 **209** 道、准确率 79.3% → **81.8%**；**人工复核量从 50% 降到 30.3%**；D 的识别 10/63 → **50/64**。
  **Handwritten A-D recognition: second optimisation round (62.9% → 76.6%).** Three new shape cues target the remaining D/B/A confusion: ① **ink in the middle band vs. the ends** — a D's bowl is hollow in the middle (only the stem and the arc), while B's two loops meet in a "waist" that adds ink there (D ≈ 0.91 vs. B ≈ 1.21, opposite directions); ② **a pointed apex means A** — A's apex is where the two strokes meet (top width 0.22) versus B's flat upper loop (0.47); the old "bottom minus top width" test missed A's with barely-splayed legs; ③ **a tall narrow hole means D** — for narrow holes, one that is tall and through-going is D's bowl (height/width ≈ 1.7) while B's loop holes are squarer (≈ 1.0). This last one **needs a top-width guard**: a printed B whose two loops merge also yields a tall narrow hole, and hole shape alone read all such B's as D (22 misreads, all B→D); adding "apex is not wide" restored zero printed misreads while keeping nearly all of the real-handwriting gain. Thresholds come from 5-fold cross-validation (73.2% generalisation on the zero-hole branch vs. ~77% in-sample).
  Net accuracy 62.9% → **76.6%** (42.9% originally); confidently-answered questions 149 → **209** at 79.3% → **81.8%**; **manual review load 50% → 30.3%**; D recall 10/63 → **50/64**.
- **e2e 对着持久库跑，断言赌了「库是干净的」**。考试持久化后，上一次 e2e 运行在 G 节留下的
  人工补录（override）会留在库里；下一次运行的 E 节（批量上传 + 内嵌名单）会被这份残留补录影响，
  「名单外的考号 → matched=False」误报红。现在 e2e 每次运行先**新建一个干净考试**再传模板，
  与残留状态彻底隔离（`test_service.py` 新增 §N 用全新考试锁「内嵌名单必须真正覆盖匹配」）。
  **The e2e suite no longer bets on a clean database.** Overrides and rosters persist in SQLite now, so
  a leftover manual fill-in from run N broke run N+1's out-of-roster assertions. The e2e now starts by
  creating a fresh exam, and `test_service.py` §N pins the "embedded roster overrides a stale one" rule
  on a brand-new exam.
- **「全班 0 分」的持久化陷阱**。判分按题号（`int`）查答案，但 JSON 只认字符串键——把整个考生字典当 blob 存
  再读回，键没归一化的话判分全查不到。持久化层统一在读写时做「题号键 ↔ 字符串」往返，并在 `test_store.py` /
  `test_service.py` 钉住「存进去再读回来分还是对的」这条不变量。
  **The "whole class scored 0" persistence trap.** Scoring looks up answers by question number (`int`), but JSON
  only allows string keys; storing the whole student dict as a blob and reading it back without normalising
  would zero every score. The store now normalises question keys on every read/write, and `test_store.py` /
  `test_service.py` pin the "store then reload still scores correctly" invariant.

### Performance / 性能
- **扫描服务识别速度提升 36 倍**：单张 A4@400dpi 从 **13.2s → 0.37s**（2 核容器实测），一个班
  50 人 × 2 面从 20 多分钟降到约 40 秒。瓶颈是光照归一化里的背景估计 —— 对 14M 像素做 159×159
  椭圆闭运算，单这一步就要 900ms，比整条识别其它部分加起来还多一个量级。背景是低频平滑场，
  改为在 1/4 分辨率上估计再插值回来，核尺寸按原图算完再换算到小图（避免小图的 `max(15,…)`
  下限引入相对更大的核），**物理邻域完全一致**：实测归一化结果与原实现逐像素最大差 9/255
  （P99 = 6），三项识别率测试仍是 100%。新增回归测试钉住这个等价性。
  **Scanner is 36× faster** — a single A4@400dpi sheet went from **13.2s to 0.37s** on a 2-core
  container (a 50-student, 2-page class: 20+ minutes → ~40 seconds). The bottleneck was the
  background estimate inside lighting normalization (a 159×159 elliptical close over 14M pixels,
  900ms on its own). Estimating it at quarter resolution and interpolating back — with the kernel
  computed at full scale then converted, so the physical neighbourhood is identical — leaves the
  normalized image within 9/255 per pixel (P99 = 6) while all three accuracy suites stay at 100%.
  A regression test now pins that equivalence.

### Fixed / 修复
- **浅涂题被误判成「多选」**。判定「一题涂了两个」时原来只看「次优选项与最优够接近」，
  但**四个印刷字母之间的 ink 极差就有 0.08 左右**（实测一道空白题是 0.079）——
  一道「A 涂得太轻」（ink 0.388）的次优是印刷字母 D（0.243），`rel2` 只比门槛高 **0.005**，
  于是被报成「A 和 D 都涂了」。现在要求次优自己也得够深（`rel2 ≥ 0.2`）才算多选，否则退回 `faint`
  （两个状态都会进复核队列，但 `faint` 指向的是正确答案）。考号列同理。
  同时补了一份**真正的「一题涂两个」**素材，把这个判定钉住。
  **Light fills were being misreported as multiple marks.** The "two options filled" test only required the
  runner-up to be *close* to the best — but the four printed letters alone differ by ~0.08 in ink (measured
  0.079 on a blank question), so a lightly-filled A (ink 0.388) whose runner-up was the letter D (0.243)
  cleared the bar by **0.005** and got reported as "A and D are both filled". The runner-up must now itself
  be inked (`rel2 ≥ 0.2`) to count as a multiple mark; otherwise it falls back to `faint`. A genuine
  double-filled fixture was added to pin the behaviour.
- **扫描服务：`data/` 目录不可写时整份识别结果被丢弃**。校对图写失败会连带把已经识别出来的答案一起变成「失败」——
  现在改成只降级：答案照常返回，接口标 `overlay: false`，前端显示原因而不是塞一个必然 404 的 `<img>`；
  写入前重新 `makedirs`，以应对挂载目录被外部改动的情况。
  **Scanner: a failed overlay write no longer discards the whole result** — answers are still returned, the
  response carries `overlay: false`, and the front end explains why instead of emitting a guaranteed-404 `<img>`.
  The directory is re-created right before each write so external mount changes can't break it.
- **扫描服务：校对图看不清**。缩略图被限制在 420px，而圈旁标的墨迹值正是核验判定对不对的依据。
  改为占满整栏 + **点击按原生分辨率放大**（Esc / 点任意处关闭）。
  **Scanner: the proof overlay was too small to read.** It now fills the column and **click-to-zooms at
  native resolution** (close with Esc or a click).
- 部署脚本不再 `rm -rf` 远程目录下的 `data/`，并改用 `--force-recreate` 重建容器 ——
  宿主 bind mount 目录被重建后，旧容器仍指向已删除的 inode，表现为「校对图偶发写不出来」。
  The deploy script no longer wipes `data/` and now uses `--force-recreate`, because a container whose
  host bind-mount directory was recreated keeps pointing at the deleted inode.

## [1.0.2] - 2026-09-25

### Added / 新增
- **导出「阅卷模板」**：工具栏新增 `🎯 阅卷模板`，一键导出 `asb-omr-template-<纸张>-<题数>q-<时间戳>.json`（例：`asb-omr-template-A4-20q-20260925-0140.json`），里面是**每个填涂圈在页面上的毫米坐标**（含四角定位点、纸张尺寸、题号与选项），供配套的 [scanner/](scanner/) 扫描识别服务做透视矫正与填涂判定。卷子里没有填涂圈模式的选择题时会明确提示，不会导出一份空模板。
  **Export a machine-readable answer-sheet template** (`asb-omr-template-*.json`) with the **millimetre coordinates of every bubble** (plus corner marks, paper size, question and option labels) for the companion [scanner/](scanner/) service to do perspective correction and bubble detection against. Warns clearly when the sheet has no bubble-mode choice questions.
- 选择题填涂圈在导出的 HTML 上带 `data-q` / `data-opt` / `data-mode` 坐标钩子，便于外部脚本或自建识别流程直接遍历 DOM。
  Bubble options now carry `data-q` / `data-opt` / `data-mode` hooks in the exported HTML for external scripts.
- **配套的扫描识别服务（`scanner/`）**：学生作答后把答题卡扫成图片，上传即可自动识读选择题、标注存疑（未涂 `blank` / 浅涂 `faint` / 多涂 `multi`），并出班级统计与 CSV。纯 OpenCV 实现、不下载模型、可离线；自带 Web 界面与 Docker 一键部署。详见 [scanner/README.md](scanner/README.md)。
  **Companion scanner service** under `scanner/`: upload scanned answer sheets to auto-read choice answers, flag doubtful ones (unanswered / light / multiple), and get class statistics plus CSV. Pure OpenCV, no model downloads, fully offline; ships a web UI and one-command Docker deploy.
- 开发辅助脚本挪进 `dev/`：`gen_omr_fixtures.cjs` 用无头 Chromium 打开真实制卡端渲染并导出 `scanner/tests/fixtures/` 的全部测试素材 —— 保证「测试过了」等于「真机也对得上」。见 [dev/README.md](dev/README.md)。
  Dev tooling moved to `dev/`: `gen_omr_fixtures.cjs` drives a headless Chromium against the real builder to regenerate every fixture under `scanner/tests/fixtures/`, so passing tests actually mean the real thing works.

## [1.0.1] - 2026-09-25

### Added / 新增
- **解答题图片直接贴进作答区**：选中解答题模块后，把鼠标停在预览区某个作答区上按 **Ctrl+V**，图片即贴进该题（点选作答区也可以，属性面板同步高亮该题卡；未悬停时贴到第 1 题）。图片**叠加在作答区内** —— 绝对定位、不占高度、不挤压横线，学生照常在旁边书写；**九宫格定位**（左上/上中/右上/左中/居中/右中/左下/下中/右下）+ 图片宽（%）可调；超出作答区的部分自动裁切，绝不溢出到下一题。「当前题」在预览区有细蓝框 + 角标提示，打印 / PDF 时不输出。
  **Paste images straight into a free-response answer area**: select the block, hover an answer area in the preview and press **Ctrl+V** (clicking works too — the properties panel highlights that question; default is question 1). The image **overlays inside the answer box** — absolutely positioned, takes no height, never squeezes the ruled lines; **9-grid positioning** plus width (%); anything beyond the box is clipped so nothing spills into the next question. The "current question" highlight is screen-only.
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
- **作答区贴图在打印时压过边框**：叠加层此前用「绝对定位 + `transform` 居中 + `max-height:100%/overflow:hidden` 裁切」，屏幕预览正常，但 **Ctrl+P 打印预览里图片会越出作答区边框**（transform 元素的裁切在打印管线里不可靠）。重构为：定位层 `inset:0` 铺满作答区、**flex 九宫格对齐（不再用 transform）**、宽度 % 与 `max-height:100%`（= 作答区高度，解析稳定）移到图片上，并由作答区盒子自带的 `overflow:hidden` 兜底裁切。实测（超高 1:3.75 图、60% 宽、100mm 盒）：屏幕 / 打印媒体 / 真实 PDF 三方几何完全一致（78.66×100.37mm，上下左右均在盒内，0.00mm 越界）。
  **Pasted images no longer cross the answer-box border in print.** The overlay used absolute positioning + `transform` centering + `max-height/overflow` clipping, which held on screen but let the image bleed over the border in Chrome's print preview. Rebuilt: the positioning layer fills the box (`inset:0`) with **flex 9-grid alignment (no transform)**, sizing moves onto the image, and the box's own `overflow:hidden` clips as a fallback. Screen / print media / real PDF now measure identical geometry with 0.00mm overflow.
- **新增题型不再重复题号**：以前新加的「选择题 / 填空题 / 解答题」一律用默认起始题号（1 / 11 / 13）—— 已有 13 题再加一个解答题还是从 13 开始，新加选择题又从 1 排到 10。现在**起始题号自动接续**：按「选择题 count + 填空题题数 + 解答题题数」累加，新块从已有总题数 +1 开始（实测：默认 13 题的卷子再加解答题 → 14，再加选择题 → 15）。手动改过的起始题号不会被改动。
  **New blocks no longer duplicate question numbers.** Added choice / fill / answer blocks used to always start at their default (1 / 11 / 13). The starting number now **continues from the existing total** (choice `count` + fill and answer question counts); manually set numbers are untouched. Measured: on a 13-question sheet a new answer block starts at 14, a further choice block at 15.
- **点解答题的任意位置都能选中该题**：以前只有作答区中间的空白区响应点击 —— 点题号行（如「13.」）或边框毫无反应。现在**整个作答盒（含题号行）**都响应悬停 / 点选，属性面板与预览高亮同步；提示里的题号也改为**卷面题号**（如「已选中第 14 题作答区」），与试卷一致。
  **Clicking anywhere on an answer box now selects that question** — previously only the blank middle area responded; clicking the question-number row (e.g. "13.") or the border did nothing. The toast now shows the **printed question number**.
- **属性面板题卡排版**：「第 1 题」和「当前」角标在窄面板里被拆成两行错位。现在标签整块不折行（放不下时整块换行），题卡行允许换行且不再互相挤压。
  **Properties-panel question-card layout**: the label and the "current" badge used to wrap mid-badge; labels are now atomic (wrap as a whole) and rows wrap cleanly.
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

[Unreleased]: https://github.com/DC1024/answer-sheet-builder/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.3
[1.0.2]: https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.2
[1.0.1]: https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.1
[1.0.0]: https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.0

---

## 发版清单 / Release checklist

> 版本号在**四个地方**各写了一份，没有任何一处是从别处推导出来的 —— **必须同时改，漏一个就会出现
> 「界面说 1.0.3、接口说 1.0.2」这种自相矛盾**。这是本项目最容易出错的一步，所以单独记在这里。

1. **改版本号（五处，全部要改）**

   | 位置 | 变量 / 内容 | 谁在用 |
   | --- | --- | --- |
   | `assets/js/core/version.js` | `APP_VERSION` | 制卡端界面、制卡端的检查更新比对 |
   | `scanner/app/__init__.py` | `__version__` | 扫描端 `/api/health`、`/api/settings`、检查更新比对 |
   | `index.html` | 首屏那行 `vX.Y.Z 已发布`（`data-zh` / `data-en` **两处都要改**） | 落地页（GitHub Pages 首屏） |
   | `README.md` / `README_EN.md` | shields 徽章里的两处 `badge/version-*` | 仓库首页 |
   | `CHANGELOG.md` | 新开一节 `## [x.y.z] - YYYY-MM-DD` + 底部链接定义 | 更新日志 |

   ```bash
   # 一个都别漏 —— 不在 CHANGELOG 里的历史版本号都应该消失
   grep -rn "1\.0\.3" assets/js/core/version.js scanner/app/__init__.py index.html \
        README.md README_EN.md CHANGELOG.md
   grep -rn "1\.0\.2" assets/js/core/version.js scanner/app/__init__.py index.html \
        README.md README_EN.md CHANGELOG.md
   # → 第一条 6 行（CHANGELOG 里两处：标题 + 链接定义）；第二条只剩 CHANGELOG 的历史
   ```

2. **跑离线测试**（不需要服务、不需要网络）

   ```bash
   cd scanner && python tests/test_omr.py && python tests/test_batch.py \
     && python tests/test_service.py && python tests/test_scoring.py \
     && python tests/test_store.py && python tests/test_update.py
   ```

3. **跑前端回归**（无头 Chromium）

   ```bash
   node dev/verify_settings.cjs            # 制卡端：设置弹窗 + 三种检查更新剧本
   node dev/verify_scanner_settings.cjs    # 扫描端：真实 Flask + 假 GitHub API
   ```

4. **本地试打包，确认 exe 真能跑**（不是只看能不能打出来）

   ```powershell
   pwsh ./packaging/windows/build.ps1 -Version x.y.z
   pwsh ./packaging/windows/ci_smoke.ps1
   ```

5. **提交 → 打标签 → 推标签**。推 `v*` 标签会触发 `.github/workflows/release-windows.yml`，
   在 `windows-latest` 上重跑一遍 build + smoke，然后把两个 zip 挂到对应的 GitHub Release 上；
   `docker.yml` 同时推镜像。**工作流只做验证与上传，版本号一定来自仓库里的文件** ——
   所以第 1 步漏改的话，CI 不会拦你，出来的包会带着旧版本号。

6. **发完确认**：Release 页面有两个 zip、镜像标签有了、`/api/health` 里的 `version` 是新号。

> 打标签前记得看一眼 `## [Unreleased]`：里面有内容就先归到新版本那一节，再把它清成 `_（暂无）_`。
