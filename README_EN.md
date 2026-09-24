# Answer Sheet Builder · 答题卡制作器

<p align="center">
  <b>Build exam answer sheets, block by block.</b><br>
  <i>像搭积木一样，制作考试答题卡。</i>
</p>

<p align="center">
  <a href="https://github.com/DC1024/answer-sheet-builder/releases/tag/v1.0.0"><img alt="version" src="https://img.shields.io/badge/version-1.0.0-blue"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-green"></a>
  <img alt="no backend" src="https://img.shields.io/badge/backend-none-success">
  <a href="https://github.com/DC1024/answer-sheet-builder/actions/workflows/docker.yml"><img alt="docker build" src="https://github.com/DC1024/answer-sheet-builder/actions/workflows/docker.yml/badge.svg"></a>
  <a href="https://github.com/DC1024/answer-sheet-builder/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/DC1024/answer-sheet-builder?style=social"></a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> &nbsp;·&nbsp; English &nbsp;·&nbsp; <a href="CHANGELOG.md">Changelog</a> &nbsp;·&nbsp; <a href="app.html">Live Demo</a>
</p>

---

## What is it?

**Answer Sheet Builder** is a **pure front-end**, visual tool for quickly producing exam answer
sheets and printing / exporting them to PDF. No backend, no sign-up, and your data never leaves
your machine — everything runs in the browser. Package it as a Docker image to deploy on any LAN.

> Live demo: open `app.html` (or the site root after a Docker deployment) to start building.

## Features

| Capability | Description |
| --- | --- |
| 🧩 **Modular question types** | Choice, fill-in-the-blank, free-response, student info and custom text blocks are independent modules — add, duplicate, delete and **drag to reorder**. |
| 📄 **Fixed-size pagination** | Paper size stays **fixed regardless of content**; content flows face by face (front → back → next page). Each A3 face is two columns (two A4-wide columns). |
| 🔤 **Bubble or handwritten** | Choice questions support **bracketed `[A]` bubbling** or **handwritten lines**; any option count is allowed (beyond 26, labels continue `AA`, `AB`, …). The column count is derived from the **measured width of a real question at render time**, so **every question fits entirely on one line**; a question that doesn't fit moves to the next row — nothing ever overflows. |
| 🎯 **Corner registration marks** | **Square** or **triangle** marks with adjustable size (2–10mm). Every face that **has content** automatically gets four corner marks; blank faces get none. Page margins are reserved from the mark size, so marks **never overlap content**; forced to render in print for scanner alignment. |
| ✎ **Nested blank items** | Supports nested items like `11(1)`, `11(2)①/②`, with **layer-aware auto-numbering** (sub `(1)(2)` → sub-sub `①②` → deeper `a) b)`); **items keep filling the same line until it is full**, then wrap. Each blank's **length** and **row spacing** are adjustable, and the spacing is **identical between questions and across wrapped lines**. |
| 📐 **Ruled areas / figures** | Free-response areas can be **blank** or **ruled** with equal spacing; **line gap** and **box height** are configurable — the height can also be **dragged live in the preview** (40–400mm; one undo step per drag), and **each question can include a figure image** (compressed locally, stored in the browser). |
| 🪪 **Student info bar** | Add/remove handwritten fields (class / name / exam number). The **exam-number grid** uses bracket squares with **digits printed inside** (up to 20 digits). Its width is capped at **1/4 of the page width** by default (adjustable 10–60%); bubbles are pushed to **3–5mm** (fillable and legible) inside the cap and the surplus goes to the fields column. The cap is relaxed only when even 3mm cannot fit — and never overflows the paper. |
| ⌨️ **Shortcuts** | **Ctrl+C / Ctrl+X / Ctrl+V** to copy, cut and paste blocks (with an Image block selected, paste an image straight from the clipboard); **Ctrl+Z / Ctrl+Y** for undo / redo (snapshot-based, up to 100 steps). |
| 🖼 **Images** | Insert images and adjust **width (%) and alignment (left / center / right)**; compressed on upload and stored **only in the browser** — no server — and they appear in print / PDF output. |
| ⬛ **Uniform black borders** | Every question block has a black border for a clear, print-friendly layout. |
| 🎛 **Common styling** | Per-module **font size** and **alignment** (left / center / right). |
| 💾 **Reusable templates** | Save / load locally (localStorage); import / export **JSON** templates. |
| 🖨 **Print / export PDF** | Print directly from the browser or save as PDF; supports **duplex (long-edge flip)**. |

## Quick Start

### Option 1 — Docker (recommended)

```bash
# 1) Build the image
docker build -t answer-sheet-builder .

# 2) Run it
docker run -d --name asb -p 8080:80 answer-sheet-builder

# 3) Open in a browser
#    http://<server-ip>:8080
```

Or with compose:

```bash
docker compose up -d
```

### Option 2 — Local / any static server

The project uses **ES Modules**, so it must be served over HTTP (you can't just double-click the HTML):

```bash
cd answer-sheet-builder
python3 -m http.server 8080
# open http://localhost:8080/app.html
```

### Option 3 — Pull the prebuilt image (GHCR)

CI **builds and pushes the image automatically** to the GitHub Container Registry on every push
to `main` or `v*` tag:

```bash
docker pull ghcr.io/dc1024/answer-sheet-builder:latest
docker run -d --name asb -p 8080:80 ghcr.io/dc1024/answer-sheet-builder:latest
# open http://<server-ip>:8080
```

> The image name is fully lowercase: `ghcr.io/dc1024/answer-sheet-builder`. Tags include `latest`,
> the branch name, `v1.2.3` / `1.2`, and `sha-xxxxxxx`.
> If pulling is denied, set the package visibility to Public under the repository **Packages** tab
> (effective after the first push).

## How to Use

1. In the left panel **"① Add question type"**, click the types you need — they are added to the structure list.
2. In **"② Answer sheet structure"**, drag the `⠿` handle to reorder, or use ↑ / ↓; click ⧉ to duplicate, ✕ to delete.
3. Select a module and configure count, style, blanks, height, font size and alignment in **"③ Properties"** on the right.
4. Pick paper (A3 / A4) and orientation (portrait / landscape) in the top bar; the preview shows **fixed-size faces**.
5. Click **"🖨 Print / Export PDF"**, choose the matching paper size and enable **duplex (long-edge flip)** in the print dialog, then save as PDF or print.

## Project Structure (modular)

```
answer-sheet-builder/
├── index.html              # Landing page (GitHub Pages home)
├── app.html                # Builder entry point
├── Dockerfile              # nginx hosting for the static assets
├── docker-compose.yml      # One-command deploy
├── assets/
│   ├── css/style.css       # All styles (including @media print)
│   └── js/
│       ├── app.js          # Main: palette / structure / props / preview / print
│       └── core/
│           ├── util.js     # esc / uid / deepClone / commonStyle
│           ├── store.js    # Global state (blocks array, CRUD, persistence)
│           ├── registry.js # Question-type registry (easy to extend)
│           └── preview.js  # Fixed-size pagination engine
│       └── blocks/         # Question-type modules (defaults / configUI / render)
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

**Adding a new question type**: create a module under `assets/js/blocks/` exporting
`{ type, name, icon, defaults, configUI, render }`, then import and add it to the array in
`core/registry.js`. No other code changes needed.

## Printing Tips

- Chrome / Edge give the best results. Set the page margin to **"None"**; the internal padding of each page is controlled by the card itself.
- In the preview, **each card = one "face"**. For A3 duplex printing, enable **"Print on both sides / Flip on long edge"** to output in the order front → back → next sheet front → …
- Every question block carries the same black border you see in the preview.

## Tech Stack

- Vanilla **ES Modules** (no framework, no build step)
- **CSS** multi-column + `repeating-linear-gradient` (rules) + `@media print`
- **Docker + nginx:alpine** hosting

## License

[MIT](LICENSE) © 2026 DC · Free and open source — use, modify and distribute freely.
