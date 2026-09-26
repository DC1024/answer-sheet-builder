# -*- coding: utf-8 -*-
"""答题卡扫描识别服务（Flask + OpenCV）。

版本号**只在这里定义一次** —— `app/update.py` 拿它跟 GitHub Release 的 tag 比，
`/api/health` 把它发给前端，Windows 免安装版也读它。发版时改这一行。

（制卡端是纯静态站点，没有 Python，它的版本号在 `assets/js/core/version.js`，
两份要一起改 —— CHANGELOG 末尾的「发版清单」里写了。）
"""

__version__ = '1.1.0'

# 更新检测的数据源：本项目自己的公开仓库
REPO = 'DC1024/answer-sheet-builder'
RELEASES_URL = 'https://github.com/{0}/releases'.format(REPO)
LATEST_API = 'https://api.github.com/repos/{0}/releases/latest'.format(REPO)
