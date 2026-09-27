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
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import LATEST_API, RELEASES_URL

DEFAULT_TIMEOUT = 8
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


def _replace_dir(src, dst):
    """把 src 整个目录覆盖到 dst（先备份旧 dst 到 dst+'.bak'）。失败回滚。

    必须在「要被替换的进程已经退出」之后调用 —— Windows 下正在跑的 exe 被锁，
    覆盖会失败。所以落地只在 bootstrap 进程里发生（旧服务已退）。
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
    p = os.path.join(data_dir, 'update_pending.json')
    try:
        with open(p, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def clear_pending(data_dir):
    p = os.path.join(data_dir, 'update_pending.json')
    try:
        os.remove(p)
    except OSError:
        pass


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
        try:
            _replace_dir(it['src'], _install_dir_of(it['install_exe']))
        except Exception as e:  # noqa: BLE001
            clear_pending(data_dir)
            return {'ok': False, 'applied': False, 'version': p.get('version', ''),
                    'error': '落地失败（{0}）：{1}'.format(it['flavor'], e),
                    'selfLocked': False}
    clear_pending(data_dir)
    if self_locked:
        return {'ok': False, 'applied': False, 'version': p.get('version', ''),
                'error': '当前进程就是要被更新的那份，请改用引导程序安装（重启服务）',
                'selfLocked': True}
    return {'ok': True, 'applied': True, 'version': p.get('version', ''), 'error': '',
            'selfLocked': False}


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


def write_pending(data_dir, src, install_exe, version, launch_args):
    """记录「待安装」：把暂存目录指向安装目录，bootstrap 据此落地。"""
    p = os.path.join(data_dir, 'update_pending.json')
    payload = {
        'version': version,
        'items': [{'flavor': SELF_FLAVOR, 'src': os.path.abspath(src),
                   'install_exe': os.path.abspath(install_exe),
                   'launch_args': list(launch_args)}],
    }
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return payload


def trigger_install(data_dir, src, version, launch_args):
    """服务内调用：把自身 exe 复制到 TEMP 做成 bootstrap，让它去落地+重启，然后本进程退出。

    必须在「旧服务即将退出」时调用 —— bootstrap 只在旧进程退了之后才能覆盖文件。
    返回是否成功发起重启（失败返回 False，且清掉 pending，不退出）。
    """
    try:
        exe = os.path.abspath(sys.executable)
        boot = os.path.join(tempfile.gettempdir(),
                            'asb-update-bootstrap.exe')
        shutil.copy2(exe, boot)
        write_pending(data_dir, src, exe, version, launch_args)
        args = [boot, '--install-pending', '--data', data_dir]
        args += _drop_flag_with_value(launch_args, '--data')
        args += [a for a in launch_args if a not in ('--install-pending',)]
        subprocess.Popen(args, close_fds=True)
        return True
    except Exception:  # noqa: BLE001
        clear_pending(data_dir)
        return False
