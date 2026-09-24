# 答题卡制作器 · Answer Sheet Builder

<p align="center">
  <b>像搭积木一样，制作考试答题卡。</b><br>
  <i>Build exam answer sheets, block by block.</i>
</p>

<p align="center">
  <a href="https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.0"><img alt="version" src="https://img.shields.io/badge/version-1.0.0-blue"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-green"></a>
  <img alt="no backend" src="https://img.shields.io/badge/backend-none-success">
  <a href="https://github.com/DC1024/answer-sheet-builder/actions/workflows/docker.yml"><img alt="docker build" src="https://github.com/DC1024/answer-sheet-builder/actions/workflows/docker.yml/badge.svg"></a>
  <a href="https://github.com/DC1024/answer-sheet-builder/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/DC1024/answer-sheet-builder?style=social"></a>
</p>

<p align="center">
  简体中文 &nbsp;·&nbsp; <a href="README_EN.md">English</a> &nbsp;·&nbsp; <a href="CHANGELOG.md">更新日志</a> &nbsp;·&nbsp; <a href="app.html">在线试用</a>
</p>

---

## 这是什么？

**答题卡制作器**是一个**纯前端**的可视化工具，用来快速制作考试答题卡并打印 / 导出 PDF。
无需后端、无需注册、数据不出本机；所有逻辑都在浏览器里完成，打包成 Docker 镜像即可在内网部署。

> 在线试用：打开 `app.html`（或在 Docker 部署后访问站点根路径）即可开始制作。

## 功能特性

| 能力 | 说明 |
| --- | --- |
| 🧩 **模块化题型** | 选择题 / 填空题 / 解答题 / 考生信息栏 / 自定义编辑区，均为独立模块，可添加、复制、删除、**拖拽排序**。 |
| 📄 **固定纸张分页** | 纸张尺寸**固定不随内容变化**；内容按「第一面 → 第二面 → 第二页第一面……」顺序填充。A3 每面双栏（左右各一张 A4 规格）。 |
| 🔤 **填涂 / 手写** | 选择题支持**中括号 `[A]` 填涂**与**横线手写**；选项数量任意（**超过 26 个用 `AA`/`AB`… 续排**）。列数在**渲染时实测**单题真实宽度后决定，**每题完整排在一行内**、排不下的整题换行，绝不溢出。 |
| 🎯 **四角定位点** | 支持**方块 / 三角**两种样式，边长可调（2–10mm）。每一面只要**有题目内容**就自动补四角定位点，空白面不加；页边距会按定位点尺寸自动预留，**绝不覆盖任何内容**；打印时强制输出底色，供阅卷机定位。 |
| ✎ **多级填空** | 支持 `11（1）`、`11（2）①/②` 这类多级小题；顶层大题首个小题紧跟题号内联、其余换行；每个空**长度**与**行间距**可调。 |
| 📐 **解答题横线 / 插图** | 作答区可选「空白」或「横线」样式，**横线间距**与**作答区高度**可调；**每题可插入题干图片**（本地压缩，仅存浏览器）。 |
| 🪪 **考生信息栏** | 可增删「班级 / 姓名 / 考号」等手写栏；**考号填涂区**为中括号方块、**框内直接显示数字**，位数上限 20。方框边长按可用宽度自动撑到 **3–5mm**（可填涂、可读），位数多时先压缩右侧手写栏、余量再由手写栏拉满，节省空间。 |
| 🖼 **图片插图** | 可插入图片并调整**宽度（%）与对齐（左/中/右）**；上传时在本机自动压缩，**仅存浏览器缓存、不上传服务器**，打印 / 导出 PDF 时正常显示。 |
| ⬛ **统一黑色边框** | 每个题型区块都带黑色边框，结构清晰、打印友好。 |
| 🎛 **通用样式** | 每个模块可单独设置**字号**与**对齐（左/中/右）**。 |
| 💾 **模板复用** | 本地保存（localStorage）、载入；支持导出 / 导入 **JSON** 模板。 |
| 🖨 **打印 / 导出 PDF** | 浏览器直接打印或另存 PDF；支持**双面长边翻转**。 |

## 界面预览

```
┌───────────────┬─────────────────────────────┬───────────────┐
│ ① 添加题型     │          预览（固定分页）      │ ③ 属性设置     │
│ 选择题/填空/…  │   ┌───────────────────┐     │ 题数 / 样式 /  │
├───────────────┤   │    A3 第一面（双栏） │     │ 空格 / 字号 /  │
│ ② 答题卡结构   │   ├───────────────────┤     │ 对齐 / 间距 …  │
│ （拖拽排序）   │   │    A3 第二面        │     │               │
└───────────────┴─────────────────────────────┴───────────────┘
```

## 快速开始

### 方式一：Docker（推荐）

```bash
# 1) 构建镜像
docker build -t answer-sheet-builder .

# 2) 运行
docker run -d --name asb -p 8080:80 answer-sheet-builder

# 3) 浏览器打开
#    http://<服务器IP>:8080
```

或使用 compose：

```bash
docker compose up -d
```

### 方式二：本地 / 任意静态服务器

项目使用 **ES Module**，必须通过 HTTP 访问（不能直接双击打开 HTML）：

```bash
cd answer-sheet-builder
python3 -m http.server 8080
# 浏览器打开 http://localhost:8080/app.html
```

### 方式三：拉取预构建镜像（GHCR）

CI 会在每次推送 `main` 或打 `v*` 标签时**自动构建并推送镜像**到 GitHub Container Registry：

```bash
docker pull ghcr.io/dc1024/answer-sheet-builder:latest
docker run -d --name asb -p 8080:80 ghcr.io/dc1024/answer-sheet-builder:latest
# 打开 http://<服务器IP>:8080
```

> 镜像名全小写：`ghcr.io/dc1024/answer-sheet-builder`。标签包含 `latest`、分支名、`v1.2.3` / `1.2`、以及 `sha-xxxxxxx`。
> 若拉取提示无权限，请在仓库 **Packages** 里把该包可见性设为 Public（首次推送后生效）。

## 使用步骤

1. 在左侧「① 添加题型」点击需要的题型，会自动加入结构列表。
2. 在「② 答题卡结构」拖动 `⠿` 手柄排序，或点 ↑ / ↓ 调整；点 ⧉ 复制、✕ 删除。
3. 选中模块，在右侧「③ 属性设置」配置题数、样式、空格、高度、字号、对齐等。
4. 顶栏选择纸张（A3 / A4）与方向（竖版 / 横版），中间预览按**固定尺寸逐面**显示。
5. 点「🖨 打印 / 导出 PDF」，在打印对话框选择对应纸张、勾选「双面（长边翻转）」，另存为 PDF 或直接打印。

## 目录结构（模块化）

```
answer-sheet-builder/
├── index.html              # 宣传页（GitHub Pages 首页）
├── app.html                # 制作器入口
├── Dockerfile              # nginx 托管静态资源
├── docker-compose.yml      # 一键部署
├── assets/
│   ├── css/style.css       # 全部样式（含打印 @media print）
│   └── js/
│       ├── app.js          # 主程序：面板 / 结构 / 属性 / 预览 / 打印装配
│       └── core/
│           ├── util.js     # esc / uid / 深拷贝 / 通用样式
│           ├── store.js    # 全局状态（blocks 数组、增删改移、持久化）
│           ├── registry.js # 题型注册表（聚合模块，便于扩展）
│           └── preview.js  # 固定纸张分页引擎
│       └── blocks/         # 各题型模块（每个含 defaults / configUI / render）
│           ├── info.js
│           ├── singleChoice.js
│           ├── fillBlank.js
│           ├── answer.js
│           ├── image.js
│           └── custom.js
├── LICENSE
├── CHANGELOG.md
└── README.md / README_EN.md
```

**扩展新题型**：在 `assets/js/blocks/` 新建一个模块（导出 `{ type, name, icon, defaults, configUI, render }`），再在 `core/registry.js` 的数组里 import 并加入即可，无需改动其他代码。

## 打印提示

- 使用 Chrome / Edge 打印效果最佳；页边距请选「**无 / None**」，每页内部留白由页面卡片自身控制。
- 预览区**每张卡片 = 一个「面」**。A3 双面打印时勾选「双面打印 / 长边翻转」，即可按「第一面 → 第二面 → 第二页第一面……」顺序输出。
- 每个题型区块都与预览一致地带上黑色边框。

## 技术栈

- 原生 **ES Module**（无框架、无构建步骤）
- **CSS** 多栏 + `repeating-linear-gradient`（横线）+ `@media print`
- 原生 **Docker + nginx:alpine** 托管

## 许可证

[MIT](LICENSE) © 2026 DC · 完全免费开源，可自由使用、修改与分发。
