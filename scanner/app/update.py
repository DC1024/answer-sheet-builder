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
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import LATEST_API, RELEASES_URL

DEFAULT_TIMEOUT = 8
# GitHub 的 API 要求带 User-Agent，否则直接 403
USER_AGENT = 'answer-sheet-builder-updater'


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
