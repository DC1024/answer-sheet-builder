# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格 —— 制卡端（答题卡制作器）Windows 免安装版。

制卡端是纯静态站点（零第三方依赖），所以这里刻意把 numpy / cv2 / torch 之类
全部排除掉，产物就是一个几 MB 的单文件 exe。

用法：
    pyinstaller --noconfirm --clean packaging/windows/cardmaker.spec
产物：
    dist/cardmaker/ASB-CardMaker.exe
"""
import os

REPO = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
LAUNCHER = os.path.join(SPECPATH, 'cardmaker_launcher.py')

# 产物名可被环境变量顶掉（build.ps1 用它给出中文名；CI 里也可强制 ASCII）
EXE_NAME = os.environ.get('ASB_WIN_EXE_NAME') or 'ASB-CardMaker'

# 站点文件随包：冻结点在 sys._MEIPASS，启动器按同名相对路径读取
datas = [
    (os.path.join(REPO, 'app.html'), '.'),
    (os.path.join(REPO, 'assets'), 'assets'),
]

# 制卡端一行第三方库都不用；不排掉的话 PyInstaller 会把构建环境里的
# numpy/cv2/torch 全拖进来（体积从 8MB 涨到几百 MB），没有任何意义。
# 注意：**不要**排 http / email —— 启动器用的 http.server 依赖它们。
EXCLUDES = [
    'numpy', 'cv2', 'torch', 'torchvision', 'torchaudio', 'PIL', 'matplotlib',
    'pandas', 'scipy', 'flask', 'jinja2', 'waitress', 'werkzeug', 'sqlite3',
    'tkinter', 'unittest', 'pydoc_data', 'setuptools', 'pip', 'pytest',
    'lib2to3', 'distutils', 'multiprocessing',
]

a = Analysis(
    [LAUNCHER],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # 保留控制台：显示本地地址，Ctrl+C 退出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
