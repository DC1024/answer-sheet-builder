# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格 —— 扫描端（答题卡扫描识别服务）Windows 免安装版。

和制卡端不同，扫描端是 Flask + OpenCV 的真后端，必须带上 numpy / opencv /
flask / waitress 及其二进制依赖，用 **onedir**（不是 onefile）：
  * onefile 每次启动都要把上百 MB 解包到 %TEMP%，开机第一次要等十几秒；
  * onedir 直接原地跑，秒开，也方便排查缺失的 DLL。

手写 CNN 是**可选**的：构建环境里有 torch 就打进去（识别精度 75.5% → 94.3%），
没有就自动跳过 —— `app/cnn_letter.py` 是惰性 import torch 的，缺了会优雅降级回
纯 OpenCV，服务照常启动。用环境变量控制：

    ASB_WIN_WITH_CNN=1  (默认) 有 torch 就打进去
    ASB_WIN_WITH_CNN=0          即使装了 torch 也不打（产物小一半以上）

用法：
    pyinstaller --noconfirm --clean packaging/windows/scanner.spec
产物：
    dist/scanner/ASB-Scanner/ASB-Scanner.exe
"""
import os

SPEC_ROOT = os.path.abspath(SPECPATH)
REPO = os.path.abspath(os.path.join(SPEC_ROOT, '..', '..'))
SCANNER = os.path.join(REPO, 'scanner')
APP = os.path.join(SCANNER, 'app')
LAUNCHER = os.path.join(SPEC_ROOT, 'scanner_launcher.py')

WITH_CNN = os.environ.get('ASB_WIN_WITH_CNN', '1') not in ('0', 'false', 'no')

# 产物名可被环境变量顶掉（build.ps1 用它给出中文名）
EXE_NAME = os.environ.get('ASB_WIN_EXE_NAME') or 'ASB-Scanner'

datas = [
    (os.path.join(APP, 'static'), 'app/static'),   # index.html / login.html
]
if WITH_CNN:
    # 权重只有 9.7MB，永远带上；能不能用取决于 torch 在不在
    datas.append((os.path.join(APP, 'hwletter_cnn.pt'), 'app'))

hiddenimports = [
    'app', 'app.server', 'app.omr', 'app.batch', 'app.stats',
    'app.scoring', 'app.store', 'app.auth', 'app.hwletter', 'app.cnn_letter',
    'waitress', 'waitress.server', 'waitress.task',
]

# 打包机才需要的东西，别跟着走。注意 **不要** 排 jinja2 / markupsafe ——
# 它们是 Flask 的硬依赖（flask.templating 在 import 期就要 jinja2）。
EXCLUDES = [
    'tkinter', 'matplotlib', 'pandas', 'scipy', 'PIL', 'notebook',
    'IPython', 'pytest', 'setuptools', 'pip', 'wheel',
]
if not WITH_CNN:
    # 只排 torch 自己的依赖，别碰 Flask 的
    EXCLUDES += ['torch', 'torchvision', 'torchaudio', 'sympy', 'networkx',
                 'filelock', 'fsspec', 'mpmath', 'symengine']

a = Analysis(
    [LAUNCHER],
    pathex=[SCANNER],       # 让 `import app` 找到 scanner/app
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir：二进制交给 COLLECT
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=EXE_NAME,
)
