# -*- coding: utf-8 -*-
"""答题卡制作器 · Windows 启动器（PyInstaller 入口）。

制卡端是一个**纯静态站点**（`app.html` + `assets/`），用 ES Module 组织脚本。
ES Module 在 `file://` 协议下会被浏览器按同源策略直接拒绝 —— 双击 `app.html`
只会得到一片白屏（控制台报 "Cross origin requests are only supported for
protocol schemes: http…"）。所以免安装版不能只发一个 html，必须自带一个
**本地 HTTP 服务**：本启动器用标准库 `http.server` 起一个只读静态服务，
再把默认浏览器指过去。

命令行（也支持同名环境变量，方便写批处理）：
    -p, --port N     监听端口，默认 0 = 由系统分配空闲端口   （环境变量 ASB_PORT）
        --host H     监听地址，默认 127.0.0.1（不触发防火墙弹窗）（环境变量 ASB_HOST）
        --no-browser 只起服务、不自动开浏览器                 （环境变量 ASB_NO_BROWSER=1）
        --root DIR   指定站点根目录（默认随包解包目录）
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

APP_TITLE = "答题卡制作器"
ENTRY = "app.html"


def root_dir() -> str:
    """静态站点根目录。

    - 冻结成 exe：PyInstaller 把随包数据解到 `sys._MEIPASS`（html/assets 就在那）。
    - 源码运行：本文件在 `packaging/windows/` 下，往上三级是仓库根。
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Handler(SimpleHTTPRequestHandler):
    """`/` → `app.html`；其余按文件路径直接映射。日志静音，别在控制台刷屏。"""

    def do_GET(self):  # noqa: N802 —— BaseHTTPRequestHandler 的命名约定
        if self.path in ("", "/", "/index.html"):
            self.path = "/" + ENTRY
        super().do_GET()

    def do_HEAD(self):  # noqa: N802
        if self.path in ("", "/", "/index.html"):
            self.path = "/" + ENTRY
        super().do_HEAD()

    def log_message(self, fmt, *args):  # noqa: A003 —— 同上
        pass


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _force_utf8_stdio() -> None:
    """stdout/stderr 强制 UTF-8。

    被重定向到管道/文件时（CI 日志、批处理），Python 会退回本地编码（简体
    中文 Windows 上是 cp936），中文输出在 UTF-8 日志里就是乱码。控制台句柄
    走的是 WriteConsoleW，不受影响，所以这里改编码对双击启动也无副作用。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 —— 拿不到 reconfigure 就算了，不该因此起不来
            pass


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog=APP_TITLE, description="答题卡制作器 · 本机网页版启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-p", "--port", type=int,
                   default=int(_env("ASB_PORT", "0") or 0),
                   help="监听端口，默认 0（由系统分配空闲端口）")
    p.add_argument("--host", default=_env("ASB_HOST", "127.0.0.1"),
                   help="监听地址，默认 127.0.0.1（仅本机）")
    p.add_argument("--root", default="", help="站点根目录（默认随包解包目录）")
    p.add_argument("--no-browser", action="store_true",
                   default=_env("ASB_NO_BROWSER").lower() in ("1", "true", "yes"),
                   help="只起服务，不自动打开浏览器")
    return p.parse_args(argv)


def _banner(url: str, root: str) -> None:
    line = "=" * 56
    text = (
        f"\n{line}\n"
        f"  {APP_TITLE} 已启动\n"
        f"{line}\n"
        f"  地址：{url}\n"
        f"  站点根：{root}\n"
        f"\n"
        f"  浏览器会自动打开。用完后回到本窗口按 Ctrl+C 退出。\n"
        f"  （直接关掉这个黑窗口也可以。）\n"
        f"{line}\n"
    )
    try:
        print(text, flush=True)
    except UnicodeEncodeError:  # 极少数非 UTF-8 控制台
        print(url, flush=True)


def main(argv=None) -> int:
    _force_utf8_stdio()
    args = parse_args(argv)
    root = os.path.abspath(args.root) if args.root else root_dir()

    entry_path = os.path.join(root, ENTRY)
    if not os.path.isfile(entry_path):
        print(f"[错误] 找不到 {ENTRY}，安装包似乎不完整：{entry_path}", flush=True)
        return 2

    host = args.host or "127.0.0.1"
    port = int(args.port or 0)

    try:
        httpd = ThreadingHTTPServer((host, port), partial(_Handler, directory=root))
    except OSError as e:
        print(f"[错误] 无法在 {host}:{port} 启动本地服务：{e}", flush=True)
        print("       端口被占用时换个端口： 答题卡制作器.exe --port 8899", flush=True)
        return 3

    httpd.daemon_threads = True
    real_port = httpd.server_address[1]
    shown_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    url = f"http://{shown_host}:{real_port}/"

    _banner(url, root)

    if not args.no_browser:
        # 等 server 真正开始 accept 再开浏览器，否则偶尔会撞上「无法连接」
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出…", flush=True)
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
