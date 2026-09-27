# -*- coding: utf-8 -*-
"""检查有没有新版本。

只用标准库 `urllib`：这个模块要被打进 Windows 免安装版，多一个依赖就多一份
打包风险，而需求只是「GET 一个 JSON，比一下版本号」。

**设计原则：任何失败都只是「查不到」，不是错误。** 学校内网很可能压根连不上
GitHub —— 那时界面该显示「暂时查不到（可能没网 / 内网）」，而不是甩一个红色
报错吓人。所以 `check()` **永远不抛异常**，失败信息放在返回值的 `error` 里。
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import LATEST_API, RELEASES_URL

DEFAULT_TIMEOUT = 8
# 起了引导程序后，等它「报到」的秒数。报到 = 它写出了 update_boot.json ——
# 说明那个进程真的起来了（而不是像 1.4.0 那样复制个裸 exe 到 TEMP、一秒就死）。
BOOT_WAIT = 25.0
# 引导程序等老服务退出的秒数。
PID_WAIT = 40.0
# update.log 超过这个大小就先清空（日志是给人排查用的，不需要留全套）。
LOG_MAX = 512 * 1024
# GitHub 的 API 要求带 User-Agent，否则直接 403
USER_AGENT = 'answer-sheet-builder-updater'

# 发布资产名里用来挑出免安装版 zip 的子串（见 build.ps1 的命名约定）
ASSET_SUBSTR = {
    'scanner': 'scanner-windows-x64',
    'cardmaker': 'cardmaker-windows-x64',
}
# 同一份代码既给扫描端也制备卡端调用：本模块只负责「扫描端」自身的自更新，
# 制卡端保持手动下载（它随用随开，且更新文件时自己没在跑，风险低）。
SELF_FLAVOR = 'scanner'


def _resolve_api_url():
    """要查的地址。可用环境变量 `ASB_UPDATE_API` 顶掉 —— 完全隔离的内网可以把它
    指向自建的镜像/代理；离线自测（和 dev/verify_scanner_settings.cjs）也靠它。
    """
    return (os.environ.get('ASB_UPDATE_API') or '').strip() or LATEST_API


def parse_version(text):
    """`v1.0.3` / `1.0.3` / `1.0.3-rc.1` → `(1, 0, 3)`。

    规则：去掉前导 v、去掉 `+build` 后缀、取 `-`/`_` 之前的主体，逐段取开头的
    数字（非数字段记 0），补足 3 段。不追求完全符合 semver —— 只需要能可靠地
    回答「新的比旧的大吗」。
    """
    s = (text or '').strip().lstrip('vV')
    s = s.split('+')[0]
    core = re.split(r'[-_]', s)[0]
    parts = []
    for piece in core.split('.'):
        m = re.match(r'^\d+', piece)
        parts.append(int(m.group()) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(latest, current):
    """latest 比 current 新？非数字/空 tag 一律当「不比」—— 宁可漏报不可误报。"""
    try:
        return parse_version(latest) > parse_version(current)
    except Exception:  # noqa: BLE001
        return False


def _blank(current, url=RELEASES_URL, error=''):
    return {'ok': False, 'current': current, 'latest': '', 'hasUpdate': False,
            'url': url, 'name': '', 'notes': '', 'publishedAt': '',
            'publishedUrl': '', 'error': error}


def check(current, api_url=None, timeout=DEFAULT_TIMEOUT):
    """查 GitHub 上最新的正式 Release。**不会抛异常。**

    返回 dict：
        ok           查成功了吗（失败时界面显示 error，而不是报错）
        current      当前版本
        latest       最新 tag，例如 `v1.0.4`
        hasUpdate    latest 是否比 current 新
        name/notes   发行版标题与正文（正文可能很长，前端自己折叠）
        url          发行版页面（有新版本时给用户点）
        publishedAt  发布时间（ISO8601）
        error        失败原因（人话，直接能显示）
    """
    out = _blank(current, error='')
    try:
        req = Request((api_url or '').strip() or _resolve_api_url(), headers={
            'User-Agent': USER_AGENT,
            'Accept': 'application/vnd.github+json',
        })
        with urlopen(req, timeout=timeout) as fh:
            raw = fh.read()
        data = json.loads(raw.decode('utf-8', 'replace'))
    except HTTPError as e:
        if e.code == 404:
            out['error'] = '这个仓库还没有发布过 Release'
        elif e.code in (403, 429):
            out['error'] = 'GitHub 暂时限制了查询频率，稍后再试'
        else:
            out['error'] = 'GitHub 返回 HTTP {0}'.format(e.code)
        return out
    except Exception as e:  # noqa: BLE001 —— 断网/DNS/超时都走这里，都只是「查不到」
        out['error'] = '连不上 GitHub（{0}）—— 内网/离线环境属正常'.format(type(e).__name__)
        return out

    if not isinstance(data, dict):
        out['error'] = 'GitHub 返回的内容看不懂'
        return out

    tag = (data.get('tag_name') or '').strip()
    out.update({
        'ok': True,
        'latest': tag,
        'name': (data.get('name') or tag).strip(),
        'url': (data.get('html_url') or RELEASES_URL).strip(),
        'publishedUrl': (data.get('html_url') or '').strip(),
        'notes': (data.get('body') or '').strip(),
        'publishedAt': (data.get('published_at') or '').strip(),
        'hasUpdate': is_newer(tag, current),
        'error': '',
    })
    return out


def list_assets(api_url=None, timeout=DEFAULT_TIMEOUT):
    """取最新正式 Release 的资产列表（含下载地址与体积）。**不抛异常。**

    返回 {'ok','tag','assets':[{name,url,size}],'error'}；失败只有 ok:false + error。
    自更新只需要其中 `*-scanner-windows-x64.zip` 那份。
    """
    out = {'ok': False, 'tag': '', 'assets': [], 'error': ''}
    try:
        req = Request((api_url or '').strip() or _resolve_api_url(), headers={
            'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json'})
        with urlopen(req, timeout=timeout) as fh:
            data = json.loads(fh.read().decode('utf-8', 'replace'))
    except HTTPError as e:
        out['error'] = 'GitHub 返回 HTTP {0}'.format(e.code)
        return out
    except Exception as e:  # noqa: BLE001
        out['error'] = '连不上 GitHub（{0}）'.format(type(e).__name__)
        return out
    if not isinstance(data, dict):
        out['error'] = 'GitHub 返回的内容看不懂'
        return out
    assets = []
    for a in (data.get('assets') or []):
        assets.append({
            'name': (a.get('name') or '').strip(),
            'url': (a.get('browser_download_url') or '').strip(),
            'size': int(a.get('size') or 0),
        })
    out.update({'ok': True, 'tag': (data.get('tag_name') or '').strip(),
                'assets': assets, 'error': ''})
    return out


def pick_asset(assets, flavor):
    """从资产列表挑出指定风味的免安装版 zip 下载地址；挑不到返回 None。"""
    sub = ASSET_SUBSTR.get(flavor)
    if not sub:
        return None
    for a in assets:
        if sub in a['name'] and a['name'].endswith('.zip') and a['url']:
            return a
    return None


# ---------------------------------------------------------------- 运行环境判定

def is_frozen():
    """是不是冻结成 exe 在跑（PyInstaller 置 sys.frozen）。源码直跑是 False。"""
    return bool(getattr(sys, 'frozen', False))


def in_container():
    """容器里不走自更新（镜像靠重新部署，替换容器文件没意义）。"""
    if os.path.exists('/.dockerenv'):
        return True
    if (os.environ.get('ASB_NO_SELF_UPDATE') or '').strip().lower() in ('1', 'true', 'yes'):
        return True
    return False


def self_update_available():
    """本机能不能自更新：仅「冻结的 Windows 免安装版」且不在容器里。

    其它情况（源码、Docker、Linux/macOS）一律 False —— 前端据此隐藏「安装」按钮，
    只保留「去发行版页面手动下载」。
    """
    if not is_frozen():
        return False
    if platform.system() != 'Windows':
        return False
    if in_container():
        return False
    return True


# ---------------------------------------------------------------- 下载 + 暂存

def _download_file(url, dest, timeout=DEFAULT_TIMEOUT, size=None, on_progress=None):
    """把 url 流式下到 dest。**不抛异常**，失败返回 {'ok':False,'error'}。

    校验：下完若已知预期体积（GitHub 资产自带 size），体积不符直接判失败 ——
    内网代理偶尔截断，宁可不装也不能装个半截包。
    """
    try:
        req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
        with urlopen(req, timeout=timeout) as src, open(dest, 'wb') as fh:
            got = 0
            while True:
                chunk = src.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if on_progress:
                    on_progress(got, size or got)
        if size and got != size:
            try:
                os.remove(dest)
            except OSError:
                pass
            return {'ok': False, 'error': '下载体积不符（期望 {0}，实际 {1}）'.format(size, got)}
        return {'ok': True, 'size': got}
    except Exception as e:  # noqa: BLE001 —— 断网/超时/代理错都走这里
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        return {'ok': False, 'error': '下载失败：{0}'.format(type(e).__name__)}


def _extract_zip(zip_path, out_dir):
    """解压并校验是个合法 zip。返回 (最外层目录, '') 或 (None, 错误)。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                return None, '压缩包损坏（{0}）'.format(bad)
            zf.extractall(out_dir)
    except Exception as e:  # noqa: BLE001
        return None, '解压失败：{0}'.format(type(e).__name__)
    top = sorted(n for n in os.listdir(out_dir)
                if os.path.isdir(os.path.join(out_dir, n)))
    if len(top) == 1:
        return os.path.join(out_dir, top[0]), ''
    return out_dir, ''


def stage_update(data_dir, assets, version, flavor=SELF_FLAVOR):
    """下载指定风味的 zip、解压到 data/updates/<version>/<flavor>/，返回暂存结果。

    返回 {'ok','error','src'?,'version'}；成功时 `src` 是解压出来的待落地目录。
    """
    asset = pick_asset(assets, flavor)
    if not asset:
        return {'ok': False, 'error': '找不到 {0} 的免安装版资产'.format(flavor)}
    base = os.path.join(data_dir, 'updates', version, flavor)
    try:
        os.makedirs(base, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': '无法创建暂存目录：{0}'.format(e)}
    zip_path = os.path.join(base, flavor + '.zip')
    res = _download_file(asset['url'], zip_path, size=asset['size'], timeout=60)
    if not res['ok']:
        return {'ok': False, 'error': res['error']}
    src, err = _extract_zip(zip_path, base)
    if err:
        return {'ok': False, 'error': err}
    try:
        os.remove(zip_path)  # 解压成功就删原始包，省空间
    except OSError:
        pass
    return {'ok': True, 'src': src, 'version': version}


# ---------------------------------------------------------------- 落地替换（重启时）

def _install_dir_of(exe):
    return os.path.dirname(os.path.abspath(exe))


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _write_json(path, payload):
    """原子落盘（写 .tmp 再 replace）—— 这是**两个进程之间**的握手文件，
    读到半截 JSON 会让服务误判「引导程序没起来」。"""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return payload


def bootlog(data_dir, text):
    """把引导程序的每一步写进 <data>/update.log。

    这个日志存在的理由很具体：引导程序是在「服务已经退出」之后跑的，它崩了
    就**没有任何界面能显示它崩了** —— 用户看到的只是「点了更新并重启，然后
    什么都没有」。留一份日志 + 一条 update_boot.json，下次开服务时能回报。
    """
    path = os.path.join(data_dir, 'update.log')
    try:
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
            os.remove(path)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write('[{0}] {1}\n'.format(
                time.strftime('%Y-%m-%d %H:%M:%S'), text))
    except OSError:
        pass


# ---- 引导程序握手文件

def _boot_path(data_dir):
    return os.path.join(data_dir, 'update_boot.json')


def write_boot_intent(data_dir, version, boot_exe, install_exe=None, launch_args=None):
    """服务退出前写：告诉引导程序「等哪个进程退、落地后拉起谁、带什么参数」。

    `reportedAt` 由引导程序回填 —— 服务**轮询它就等于在确认「引导程序真的
    起来了」**。这正是 1.4.0 缺的那一环：那时把 sys.executable 复制成
    `%TEMP%\\asb-update-bootstrap.exe`（一个脱离 `_internal` 的裸 exe）再执行，
    它在加载 python DLL 时就死了，服务却照样 `os._exit(0)` —— 于是没人落地。
    """
    return _write_json(_boot_path(data_dir), {
        'version': version,
        'bootExe': os.path.abspath(boot_exe),
        'installExe': os.path.abspath(install_exe) if install_exe else '',
        'launchArgs': list(launch_args or []),
        'servicePid': os.getpid(),
        'startedAt': time.time(),
        'reportedAt': 0,
    })


def read_boot_intent(data_dir):
    return _read_json(_boot_path(data_dir))


def mark_boot_reported(data_dir):
    """引导程序启动后**第一件事**：报到。服务等到它才敢退出。"""
    d = _read_json(_boot_path(data_dir)) or {}
    d['reportedAt'] = time.time()
    return _write_json(_boot_path(data_dir), d)


def boot_reported(data_dir):
    d = _read_json(_boot_path(data_dir)) or {}
    return bool(d.get('reportedAt'))


def record_bootstrap(data_dir, info):
    """记下引导程序的事故（退出码 / 人话原因），下次开服务时回报给界面。"""
    d = _read_json(_boot_path(data_dir)) or {}
    d['failure'] = dict(info)
    return _write_json(_boot_path(data_dir), d)


def bootstrap_failure(data_dir):
    """上次引导程序留下的失败记录（没有则 None）。"""
    d = _read_json(_boot_path(data_dir)) or {}
    f = d.get('failure')
    return dict(f) if isinstance(f, dict) else None


def clear_bootstrap(data_dir):
    """清掉握手文件。**只在发起新一次安装前 / 成功回报后清** —— 失败记录要
    留到界面读到为止，不能每次启动都把它抹了。"""
    try:
        os.remove(_boot_path(data_dir))
    except OSError:
        pass


def wait_for_pid_exit(pid, timeout=PID_WAIT):
    """等 pid 退出（最多 timeout 秒）。返回它是否真的退了。

    必须等：Windows 会锁住正在运行的 exe，老服务没退就替换会失败。
    用 `OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject(h, 0)` 而不是
    `os.kill(pid, 0)` —— 后者在 Windows 上会**真的去杀**那个进程。
    """
    if pid <= 0:
        return True
    if platform.system() != 'Windows':
        return True
    try:
        import ctypes
        from ctypes import wintypes
        SYNCHRONIZE, WAIT_TIMEOUT = 0x00100000, 0x00000102
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        deadline = time.time() + max(0.0, timeout)
        while True:
            h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not h:
                return True          # 打不开 = 进程已不在
            try:
                if k32.WaitForSingleObject(h, 0) != WAIT_TIMEOUT:
                    return True      # 已 signaled = 退了
            finally:
                k32.CloseHandle(h)
            if time.time() >= deadline:
                return False
            time.sleep(0.2)
    except Exception:  # noqa: BLE001 —— 判不出来就按「已退」处理，靠替换阶段的异常兜住
        return True


def _replace_dir(src, dst):
    """把 src 整个目录覆盖到 dst（先备份旧 dst 到 dst+'.bak'）。失败回滚。

    必须在「要被替换的进程已经退出」之后调用 —— Windows 下正在跑的 exe 被锁，
    覆盖会失败。所以落地只在 bootstrap 进程里发生（旧服务已退）。

    注意 src 可能是**正在运行引导程序的那个目录**（我们用暂存版本当引导程序，
    免得再复制 590MB）：Windows 上「运行中的 exe 被占用」禁的是**写**，读/复制
    不受影响，所以 copytree 一个正在跑的 onedir 是安全的。
    """
    bak = dst + '.bak'
    if os.path.exists(bak):
        shutil.rmtree(bak, ignore_errors=True)
    if os.path.exists(dst):
        os.rename(dst, bak)
    try:
        shutil.copytree(src, dst)
    except Exception:  # noqa: BLE001 —— 复制中断，把备份还原回去
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)
        if os.path.exists(bak):
            os.rename(bak, dst)
        raise


def read_pending(data_dir):
    return _read_json(os.path.join(data_dir, 'update_pending.json'))


def clear_pending(data_dir):
    try:
        os.remove(os.path.join(data_dir, 'update_pending.json'))
    except OSError:
        pass


def resolve_src(src, install_exe):
    """挑出「真正要覆盖到安装目录的那一层」，返回 (目录, 错误)。

    `_extract_zip` 正常会剥掉包里那层顶层目录，于是 src 里就该有 exe。但它剥不出来
    时（包里有多个顶层目录）会把**解压根目录**返回回来 —— 那一层里只有个子目录、
    没有 exe。直接拿它去覆盖安装目录，会把安装目录换成一个空的框架（exe 全没了）。
    这里先确认「这一层里真有 exe」，没有就往下找一层唯一目录。
    """
    if not src or not os.path.isdir(src):
        return None, '暂存目录不见了'
    if staged_exe(src, install_exe):
        return src, ''
    subs = [n for n in sorted(os.listdir(src))
            if os.path.isdir(os.path.join(src, n))]
    for n in subs:
        cand = os.path.join(src, n)
        if staged_exe(cand, install_exe):
            return cand, ''
    return None, '暂存目录里没有可执行文件（压缩包结构不对？）'


def apply_pending(data_dir):
    """按 pending.json 把暂存版本落到安装目录。**在启动器里、服务起来之前调用。**

    旧服务已经退出，这里覆盖文件不会被锁；但若本进程恰好就是要被替换的那份
    （正常双击启动却还留着 pending，且未走 bootstrap），跳过该项以免锁死自己。
    返回 {'ok','applied','version','error','selfLocked'}。
    """
    p = read_pending(data_dir)
    if not p:
        return {'ok': True, 'applied': False, 'version': '', 'error': '', 'selfLocked': False}
    self_locked = False
    for it in (p.get('items') or []):
        if os.path.abspath(it['install_exe']) == os.path.abspath(sys.executable):
            # 不能替换正在运行的自己 —— 交给 bootstrap 进程来做
            self_locked = True
            continue
        if not os.path.isdir(it['src']):
            clear_pending(data_dir)
            return {'ok': False, 'applied': False, 'version': p.get('version', ''),
                    'error': '暂存目录不见了：{0}'.format(it['src']),
                    'selfLocked': False}
        real, why = resolve_src(it['src'], it['install_exe'])
        if not real:
            clear_pending(data_dir)
            return {'ok': False, 'applied': False, 'version': p.get('version', ''),
                    'error': '暂存内容不完整：{0}'.format(why), 'selfLocked': False}
        try:
            _replace_dir(real, _install_dir_of(it['install_exe']))
        except Exception as e:  # noqa: BLE001
            clear_pending(data_dir)
            return {'ok': False, 'applied': False, 'version': p.get('version', ''),
                    'error': '落地失败（{0}）：{1}'.format(it.get('flavor', '?'), e),
                    'selfLocked': False}
    clear_pending(data_dir)
    if self_locked:
        return {'ok': False, 'applied': False, 'version': p.get('version', ''),
                'error': '当前进程就是要被更新的那份，请改用引导程序安装（重启服务）',
                'selfLocked': True}
    return {'ok': True, 'applied': True, 'version': p.get('version', ''), 'error': '',
            'selfLocked': False}


# ---------------------------------------------------------------- 引导程序选谁

def staged_exe(src, install_exe):
    """在暂存目录里挑出「要落地的那份 exe」。找不到返回 None。"""
    if not src or not os.path.isdir(src):
        return None
    want = os.path.basename(install_exe or '').lower()
    names = [n for n in sorted(os.listdir(src))
             if n.lower().endswith('.exe')
             and os.path.isfile(os.path.join(src, n))]
    if not names:
        return None
    for n in names:
        if want and n.lower() == want:
            return os.path.join(src, n)
    return os.path.join(src, names[0])


def bootstrap_exe(src, install_exe):
    """挑一个「真的能跑起来」的引导程序，返回 exe 路径；挑不出来返回 None。

    **这是 1.4.0「更新并重启没反应」的根因所在。** 免安装版是 PyInstaller
    *onedir*：exe 旁边必须有 `_internal\\python313.dll` 等一堆文件。原来是把
    `sys.executable` 单独 copy 到 `%TEMP%\\asb-update-bootstrap.exe` —— 裸 exe
    找不到同级 `_internal`，进程在加载 python DLL 时就死了
    （`Failed to load Python DLL '...\\_internal\\python313.dll'`），
    pending.json 因此永远没人处理。

    所以优先选**暂存目录里那份新版的 exe**：它自带完整 `_internal`，能原地跑，
    又正好在安装目录**之外**（替换安装目录不会被自己的文件锁挡住），还省掉
    再复制一份几百 MB 的安装目录。
    """
    cand = staged_exe(src, install_exe)
    if cand and os.path.isdir(os.path.join(os.path.dirname(cand), '_internal')):
        return cand
    # 兜底：onefile 产物（单个 exe 自成一体）复制到 TEMP 仍能跑。onedir 走这条路
    # 会崩 —— 但现在崩了会被 trigger_install 的握手检测到并回报，不再无声无息。
    try:
        boot = os.path.join(tempfile.gettempdir(), 'asb-update-bootstrap.exe')
        shutil.copy2(os.path.abspath(sys.executable), boot)
        return boot
    except Exception:  # noqa: BLE001
        return None


# ---- 收尾：新版本起来了才算更新成功，这时才敢删备份

def post_boot_maintenance(data_dir, install_dir=None):
    """新版本成功启动后调用：删掉 `*.bak` 备份和已消费的暂存目录。

    时机很关键 —— 备份要留到「新版本**确实跑起来了**」才删，这样万一新版启动
    就崩，`.bak` 还在，人工改名就能回滚。暂存目录则等新进程来删（引导程序
    当时还跑在里面，删不掉自己的 exe）。
    """
    freed = []
    if install_dir:
        bak = os.path.abspath(install_dir) + '.bak'
        if os.path.isdir(bak):
            shutil.rmtree(bak, ignore_errors=True)
            if not os.path.exists(bak):
                freed.append(os.path.basename(bak))
    up = os.path.join(data_dir, 'updates')
    if os.path.isdir(up):
        shutil.rmtree(up, ignore_errors=True)
        if not os.path.exists(up):
            freed.append('updates/')
    return freed


# ---------------------------------------------------------------- 触发安装（服务内）

_DOWNLOAD = {'lock': threading.Lock(), 'running': False, 'done': False,
             'error': '', 'version': '', 'progress': 0, 'total': 0, 'src': None}


def download_state():
    with _DOWNLOAD['lock']:
        return {k: _DOWNLOAD[k] for k in
                ('running', 'done', 'error', 'version', 'progress', 'total', 'src')}


def _drop_flag_with_value(args, flag):
    """去掉 args 里的 `--flag value` 这种「带值参数」。"""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a == flag:
            skip = True
            continue
        out.append(a)
    return out


def _run_stage(data_dir, assets, version, on_done=None):
    res = stage_update(data_dir, assets, version, SELF_FLAVOR)
    with _DOWNLOAD['lock']:
        if res['ok']:
            _DOWNLOAD['done'] = True
            _DOWNLOAD['version'] = version
            _DOWNLOAD['src'] = res.get('src')
        else:
            _DOWNLOAD['error'] = res['error']
        _DOWNLOAD['running'] = False
    if res['ok'] and on_done:
        try:
            on_done(version, res.get('src'))
        except Exception:  # noqa: BLE001 —— 回调失败不该把后台线程炸了
            pass


def start_download(data_dir, assets, version, on_done=None):
    """后台下载+暂存；已在跑或已暂存过同版本就忽略。返回是否新启动。"""
    with _DOWNLOAD['lock']:
        if _DOWNLOAD['running']:
            return False
        if _DOWNLOAD['done'] and _DOWNLOAD['version'] == version:
            # 已暂存过：仍允许 on_done（比如自动安装还没触发）
            if on_done:
                try:
                    on_done(version, _DOWNLOAD['src'])
                except Exception:  # noqa: BLE001
                    pass
            return False
        _DOWNLOAD['running'] = True
        _DOWNLOAD['done'] = False
        _DOWNLOAD['error'] = ''
        _DOWNLOAD['version'] = version
        _DOWNLOAD['progress'] = 0
        _DOWNLOAD['total'] = 0
        _DOWNLOAD['src'] = None
    t = threading.Thread(target=_run_stage, args=(data_dir, assets, version, on_done),
                         daemon=True)
    t.start()
    return True


def write_pending(data_dir, src, install_exe, version, launch_args, boot_exe=None):
    """记录「待安装」：把暂存目录指向安装目录，bootstrap 据此落地。

    `boot_exe` 是**实际要被执行的引导程序**（见 `bootstrap_exe()`）。存进
    pending 是为了让下一次「正常双击启动」也能知道上次备选方案是谁 ——
    排查时打开这个 json 就能看明白当时打算怎么落地。
    """
    payload = {
        'version': version,
        'items': [{'flavor': SELF_FLAVOR, 'src': os.path.abspath(src),
                   'install_exe': os.path.abspath(install_exe),
                   'boot_exe': os.path.abspath(boot_exe) if boot_exe else '',
                   'launch_args': list(launch_args)}],
    }
    return _write_json(os.path.join(data_dir, 'update_pending.json'), payload)


def _boot_args(data_dir, boot_exe, launch_args):
    """拼引导程序自己的命令行：只做落地 + 拉起，不启动服务。"""
    args = [boot_exe, '--install-pending', '--data', data_dir]
    args += _drop_flag_with_value(launch_args, '--data')
    args += [a for a in launch_args if a not in ('--install-pending',)]
    return args


def trigger_install(data_dir, src, version, launch_args):
    """服务内调用：起引导程序去落地 + 重启，本进程随后退出。

    与 1.4.0 的关键区别是**握手**，而不是「`Popen` 成功就当成功」：

      1. 选一个真能跑的引导程序（`bootstrap_exe`，优先暂存目录里的新版 exe，
         它自带 `_internal`）；
      2. 先写 `update_pending.json` + `update_boot.json`（含本进程 pid）；
      3. `Popen` 起引导程序，然后**轮询 `update_boot.json` 的 `reportedAt`** ——
         引导程序起来的第一件事就是回填它。只有真等到回填，才认为「它会干活」；
      4. 等不到就带超时字眼返回 False，让前端显示「安装失败：…」，
         **而不是**像以前那样默默退出、留下一个没人处理的 pending。

    返回 (是否成功发起, 失败原因)。
    """
    try:
        exe = os.path.abspath(sys.executable)
        boot = bootstrap_exe(src, exe)
        if not boot:
            return False, '找不到可用的引导程序（暂存目录里没有 exe）'
        write_pending(data_dir, src, exe, version, launch_args, boot_exe=boot)
        clear_bootstrap(data_dir)
        write_boot_intent(data_dir, version, boot, install_exe=exe, launch_args=launch_args)
        subprocess.Popen(_boot_args(data_dir, boot, launch_args), close_fds=True)
    except Exception as e:  # noqa: BLE001
        clear_pending(data_dir)
        clear_bootstrap(data_dir)
        return False, '发起安装失败：{0}'.format(e)

    # 等引导程序报到 —— 这是「它真的活着」的唯一证据
    deadline = time.time() + BOOT_WAIT
    while time.time() < deadline:
        if boot_reported(data_dir):
            return True, ''
        time.sleep(0.2)

    failed = bootstrap_failure(data_dir)
    clear_pending(data_dir)
    if failed:
        return False, '引导程序启动即失败（退出码 {0}）：{1}'.format(
            failed.get('exitCode'), failed.get('error') or '见 update.log')
    if not os.path.exists(boot):
        return False, '选定的引导程序不见了：{0}'.format(boot)
    return False, ('引导程序 {0} 秒内没有响应（多半是没能启动）。'
                   '可查看 update.log').format(int(BOOT_WAIT))
