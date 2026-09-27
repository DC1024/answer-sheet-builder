# -*- coding: utf-8 -*-
"""答题卡扫描识别服务 · Windows 启动器（PyInstaller 入口）。

和制卡端不同，扫描端本身就是个 Flask 应用（`scanner/app/server.py`）。
免安装版要做的事只有三件：

1. **先把可写数据目录定下来**——`server.py` 默认把 SQLite 和校对图放在
   `<app>/../data/`，容器里那是 bind mount，冻结成 exe 时那却是 PyInstaller
   的临时解包目录（进程一退就没了，等于每次开都清空）。所以这里在 import
   app **之前**就设好 `ASB_DATA` / `ASB_DB`，指到 `%LOCALAPPDATA%\\asb-scanner`。
2. **用 waitress 起服务**（Flask 自带的 dev server 是单线程 + 会打印一堆警告，
   一个班 50 张卷子并发上传会卡）。
3. 把浏览器打开到首页（首次运行会引导创建管理员账号）。

命令行（也支持同名环境变量，方便写批处理）：
    -p, --port N     首选端口，默认 8081；被占用时自动往后找   （环境变量 ASB_PORT）
        --host H     监听地址，默认 127.0.0.1；
                     要让同网段其他机器访问就写 0.0.0.0        （环境变量 ASB_HOST）
        --data DIR   数据目录（库 + 校对图）                    （环境变量 ASB_DATA）
        --no-cnn     跳过手写 CNN，直接用纯 OpenCV 识别（省内存）（环境变量 ASB_NO_CNN=1）
        --no-browser 只起服务、不自动开浏览器                   （环境变量 ASB_NO_BROWSER=1）
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import webbrowser

APP_TITLE = "答题卡扫描识别服务"
PREFERRED_PORT = 8081
PORT_TRIES = 20
# waitress 的 ident 会原样变成 HTTP 响应头里的 `Server:` —— HTTP 头只能是
# latin-1，塞中文进去会让**每一个**响应在 build_response_header 里抛
# UnicodeEncodeError，然后所有请求 500。所以这里必须是纯 ASCII。
SERVER_IDENT = "asb-scanner"


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


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_flag(name: str) -> bool:
    return _env(name).lower() in ("1", "true", "yes", "on")


def _default_data_dir() -> str:
    """%LOCALAPPDATA%\\asb-scanner\\data —— 每个用户各自一份，卸载重装不丢库。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "asb-scanner", "data")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog=APP_TITLE, description="答题卡扫描识别服务 · 本机网页版启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-p", "--port", type=int,
                   default=int(_env("ASB_PORT", str(PREFERRED_PORT)) or PREFERRED_PORT),
                   help=f"首选端口，默认 {PREFERRED_PORT}；被占用时自动往后找")
    p.add_argument("--host", default=_env("ASB_HOST", "127.0.0.1"),
                   help="监听地址，默认 127.0.0.1（仅本机）")
    p.add_argument("--data", default=_env("ASB_DATA"),
                   help="数据目录（默认 %%LOCALAPPDATA%%\\asb-scanner\\data）")
    p.add_argument("--no-cnn", action="store_true", default=_env_flag("ASB_NO_CNN"),
                   help="跳过手写 CNN，直接用纯 OpenCV 识别")
    p.add_argument("--no-browser", action="store_true", default=_env_flag("ASB_NO_BROWSER"),
                   help="只起服务，不自动打开浏览器")
    # 内部使用：被「安装更新」的引导程序调用，落地更新后拉起新版本并退出，不启动服务
    p.add_argument("--install-pending", action="store_true", default=False,
                   help=argparse.SUPPRESS)
    return p.parse_args(argv)


def _prepare_env(args: argparse.Namespace) -> str:
    """在 import app 之前把数据目录钉死，返回最终使用的目录。"""
    data = os.path.abspath(args.data) if args.data else _default_data_dir()
    os.makedirs(data, exist_ok=True)
    os.environ["ASB_DATA"] = data
    os.environ.setdefault("ASB_DB", os.path.join(data, "asb.db"))
    if args.no_cnn:
        # server._get_cnn_model() 的加载条件就是「权重文件在不在」，
        # 把路径指到一个不存在的地方即可显式降级，不用动 torch 本身。
        os.environ["ASB_CNN_MODEL"] = os.path.join(data, "__cnn_disabled__")
    return data


def _pick_port(host: str, prefer: int) -> int:
    """从 prefer 起往后找一个能绑上的端口。全占满则返回 prefer（让调用方报错）。"""
    for i in range(PORT_TRIES):
        p = prefer + i
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return prefer


def _banner(url: str, data: str, cnn: bool, db: str) -> None:
    line = "=" * 64
    text = (
        f"\n{line}\n"
        f"  {APP_TITLE} 已启动\n"
        f"{line}\n"
        f"  地址：  {url}\n"
        f"  数据库：{db}\n"
        f"  校对图：{os.path.join(data, '<随机ID>.png')}\n"
        f"  手写识别：{'CNN + OpenCV 交叉验证' if cnn else 'OpenCV（未启用 CNN）'}\n"
        f"\n"
        f"  首次运行请在网页里创建管理员账号。\n"
        f"  用完后回到本窗口按 Ctrl+C 退出。\n"
        f"{line}\n"
    )
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(url, flush=True)


def _bootstrap_apply_and_relaunch(data: str) -> int:
    """引导模式：旧服务已退出，把暂存的新版本落到安装目录，再拉起新版本后退出。

    只在「被更新的那份 exe 已经不在运行」时才能覆盖文件（Windows 会锁住正在跑的 exe），
    所以这个分支由 trigger_install 复制出来的 bootstrap 进程跑，而不是正在服务的进程。
    """
    from app import update as upd  # noqa: E402

    p = upd.read_pending(data)
    if not p:
        return 0
    items = p.get("items") or []
    res = upd.apply_pending(data)
    if not res.get("ok"):
        print("落地更新失败：%s" % res.get("error"), flush=True)
        return 1
    print("已落地更新：%s，正在拉起新版本…" % res.get("version"), flush=True)
    for it in items:
        if it.get("flavor") == upd.SELF_FLAVOR:
            try:
                subprocess.Popen([it["install_exe"]] + list(it.get("launch_args") or []),
                                 close_fds=True)
            except Exception as e:  # noqa: BLE001
                print("拉起新版本失败：%s" % e, flush=True)
            break
    return 0


def main(argv=None) -> int:
    _force_utf8_stdio()
    args = parse_args(argv)
    data = _prepare_env(args)

    # 引导模式：只落地更新 + 拉起新版本，不启动当前服务
    if args.install_pending:
        return _bootstrap_apply_and_relaunch(data)

    # 正常启动：若上次更新留下 pending 且本进程不是「要被更新的那份」，先落地
    # （正常双击启动通常是 no-op；真正的落地发生在上面的引导分支里）
    try:
        from app import update as upd  # noqa: E402
        res = upd.apply_pending(data)
        if res.get("applied"):
            print("已应用待更新：%s" % res.get("version"), flush=True)
    except Exception as e:  # noqa: BLE001
        print("应用待更新失败：%s" % e, flush=True)

    cnn_on = not args.no_cnn

    # 必须在 ASB_DATA / ASB_DB 定型之后再 import —— server.py 在模块级建库。
    from waitress import serve  # noqa: E402
    from app.server import create_app  # noqa: E402

    application = create_app()
    db_path = os.environ["ASB_DB"]

    host = args.host or "127.0.0.1"
    prefer = int(args.port or PREFERRED_PORT)

    port = _pick_port(host, prefer)
    shown_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    url = f"http://{shown_host}:{port}/"

    _banner(url, data, cnn_on, db_path)
    if port != prefer:
        print(f"  提示：端口 {prefer} 已被占用，改用 {port}。\n", flush=True)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        serve(application, host=host, port=port, threads=8, ident=SERVER_IDENT)
        # 注意：ident 不能写 APP_TITLE —— 中文进 HTTP 头会让每个响应都 500（见文件头常量注释）
    except KeyboardInterrupt:
        print("\n正在退出…", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
