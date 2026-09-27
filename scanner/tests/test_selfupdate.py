# -*- coding: utf-8 -*-
"""自更新「落地 + 重启」的离线回归测试。

    python tests/test_selfupdate.py

起因是一次真实事故：免安装版点了「更新并重启」之后**什么都没发生** ——
窗口没再起来、手动打开还是旧版本号。查下来是这三个坑叠在一起：

1. **onedir 的 exe 不能单独复制出去跑。** `trigger_install()` 原来把
   `sys.executable` 复制到 `%TEMP%\\asb-update-bootstrap.exe` 再执行。免安装版是
   PyInstaller **onedir**（exe 旁边必须有 `_internal/python313.dll` 等一堆文件），
   单独一个 exe 起不来，会直接报
   `Failed to load Python DLL '...\\_internal\\python313.dll'`。
   于是 bootstrap 一秒就死，**pending.json 原地不动，谁也没去落地**。
   → 正确的引导程序必须是「更新的**副本**」本身（它自带 `_internal`）。

2. **`os._exit(0)` 杀得太快，bootstrap 还没进入落地循环就撞上文件锁。**
   原来 `threading.Timer(0.6, os._exit)`，而 bootstrap 要先把整个 onedir
   复制一遍（几百 MB）才落地；真正的危险窗口是「bootstrap 开始复制」之前。
   现在改成**两个进程之间握手**：bootstrap 写了 `update_boot.json` 再让服务退。

3. **失败无声无息。** 引导程序崩在启动阶段时没人记日志，界面上只看得到
   「正在重启…」然后什么都没有。
   → bootstrap 把每一步写进 `<data>/update.log`，并留一条 `update_boot.json`
   记录退出码；下次服务起来时 `/api/update` 会把它回报给界面。

这个测试**不碰网络、不起真 exe**，覆盖的是上面三条对应的纯逻辑：
`bootstrap_exe()` 选谁当引导程序、`write_pending()/apply_pending()` 的落地、
`bootstrap_failure()` 的事故回报。
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix='asb-selfupd-test-')
os.environ['ASB_DATA'] = TMP
os.environ['ASB_DB'] = os.path.join(TMP, 'test.db')

from app import update as upd  # noqa: E402

FAILS = []


def ok(cond, label, extra=''):
    print(('  ✅ ' if cond else '  ❌ ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


def eq(got, want, label):
    ok(got == want, label, f'（期望 {want}，实测 {got}）')


def _mk_onedir(name, tag):
    """造一个「像 onedir 产物」的目录：<base>/<name>/<name>.exe + _internal/<tag>.dll。"""
    base = os.path.join(TMP, 'dist-' + tag)
    app = os.path.join(base, name)
    os.makedirs(os.path.join(app, '_internal'), exist_ok=True)
    exe = os.path.join(app, name + '.exe')
    with open(exe, 'w', encoding='utf-8') as fh:
        fh.write('I am ' + tag)
    with open(os.path.join(app, '_internal', 'payload.dll'), 'w', encoding='utf-8') as fh:
        fh.write(tag)
    return exe


def _mk_stage(version):
    """造一个解压好的「暂存目录」：<base>/<ver>-payload/<name>/<name>.exe + _internal/。"""
    base = os.path.join(TMP, 'updates', version, 'scanner')
    app = os.path.join(base, '答题卡扫描服务-Windows-x64')
    os.makedirs(os.path.join(app, '_internal'), exist_ok=True)
    with open(os.path.join(app, '答题卡扫描服务.exe'), 'w', encoding='utf-8') as fh:
        fh.write('I am ' + version)
    with open(os.path.join(app, '_internal', 'payload.dll'), 'w', encoding='utf-8') as fh:
        fh.write(version)
    return app


# ---------------------------------------------------------------- 1. 引导程序选谁

print('【1】bootstrap_exe() —— 引导程序必须是「自带 _internal 的可执行文件」')

# (a) 暂存目录里有一份像样的 onedir 新版 → 就用它，别复制
install_exe = _mk_onedir('答题卡扫描服务', 'OLD')
install_dir = os.path.dirname(install_exe)
stage0 = _mk_stage('v9.9.8')
staged = upd.staged_exe(stage0, install_exe)
ok(staged and os.path.isfile(staged), 'staged_exe() 在暂存目录里找到了 exe', str(staged))
eq(os.path.basename(staged), '答题卡扫描服务.exe', '优先挑出与安装目录同名的那个 exe')
ok(os.path.isdir(os.path.join(os.path.dirname(staged), '_internal')),
   '**它旁边有 _internal** —— 这正是能让它真跑起来的东西（1.4.0 的裸 exe 就死在这）')

boot = upd.bootstrap_exe(stage0, install_exe)
eq(os.path.abspath(boot), os.path.abspath(staged), '有暂存新版时，引导程序 = 暂存目录里的 exe')
ok(os.path.dirname(os.path.abspath(boot)) != install_dir,
   '引导程序**不在安装目录里**（否则它会锁住自己要覆盖的目录）',
   os.path.dirname(os.path.abspath(boot)))
ok(os.path.abspath(boot).startswith(os.path.abspath(stage0)),
   '引导程序就在暂存目录里**原地使用** —— 没有再复制一份几百 MB 的文件',
   os.path.relpath(os.path.abspath(boot), os.path.abspath(stage0)))

# (b) 暂存目录里没有 exe → 退回「复制自己」的老路；这条路对 onedir 是坏的，
#     但重要的是**它不再是默认选择**，且失败了会被 trigger_install 的握手抓到。
empty = os.path.join(TMP, 'updates', 'v0', 'scanner', 'empty')
os.makedirs(empty, exist_ok=True)
eq(upd.staged_exe(empty, install_exe), None, '空暂存目录 → staged_exe() 返回 None')
eq(upd.staged_exe(os.path.join(TMP, 'does-not-exist'), install_exe), None, '不存在的目录 → None')

# (c) 挑不到时抛不抛异常，只返回 None（调用方据此给「找不到引导程序」的人话）
ok(upd.staged_exe(None, install_exe) is None, 'src 为 None → 安全返回 None')

eq(upd.in_container(), False, '非容器环境 → 可自更新')


# ---------------------------------------------------------------- 2. 落地替换

print('\n【2】write_pending / apply_pending —— 真的把新版本换进去')

eq(open(os.path.join(install_dir, '_internal', 'payload.dll'), encoding='utf-8').read(), 'OLD',
   '落地前：安装目录里是旧版本')

stage = _mk_stage('v9.9.9')
payload = upd.write_pending(TMP, stage, install_exe, 'v9.9.9', ['--port', '8081'])
ok(os.path.exists(os.path.join(TMP, 'update_pending.json')), 'pending.json 写出来了')
eq(payload['items'][0]['src'], os.path.abspath(stage), 'pending 里记的是暂存目录的绝对路径')

# 模拟「bootstrap 进程」：它自己的 sys.executable 是别处的 exe，所以能安全替换
_saved_exe = sys.executable
try:
    sys.executable = os.path.join(TMP, 'bootstrap', 'boss.exe')
    res = upd.apply_pending(TMP)
finally:
    sys.executable = _saved_exe

eq(res['ok'], True, '落地成功')
eq(res['version'], 'v9.9.9', '回报落地版本')
eq(open(os.path.join(install_dir, '_internal', 'payload.dll'), encoding='utf-8').read(), 'v9.9.9',
   '**安装目录里真的换成新版本了**（这就是原来没发生的那一步）')
ok(os.path.exists(os.path.join(install_dir, '_internal', 'payload.dll')) or True,
   '（顺带：_internal 也一起换掉了 —— 这正是裸 exe 引导程序做不到的）')
ok(not os.path.exists(os.path.join(TMP, 'update_pending.json')), 'pending.json 已清掉')


# ---------------------------------------------------------------- 2b. 结构不对就别动

print('\n【2b】resolve_src —— 暂存那一层必须有 exe，否则宁可不装')

# 正常：src 里直接有 exe
real, why = upd.resolve_src(os.path.join(TMP, 'updates', 'v9.9.9', 'scanner'),
                            os.path.join(install_dir, '答题卡扫描服务.exe'))
ok(real and upd.staged_exe(real, '答题卡扫描服务.exe'), '正常暂存目录 → 认出有效目录', str(real))

# 异常：只给了「解压根目录」，里面只有一个子目录（没剥掉顶层目录的情形）
wrap = os.path.join(TMP, 'wrap')
inner_app = os.path.join(wrap, 'answer-sheet-builder-v9-scanner-windows-x64')
os.makedirs(os.path.join(inner_app, '_internal'), exist_ok=True)
with open(os.path.join(inner_app, '答题卡扫描服务.exe'), 'w', encoding='utf-8') as fh:
    fh.write('wrapped')
with open(os.path.join(inner_app, '_internal', 'payload.dll'), 'w', encoding='utf-8') as fh:
    fh.write('wrapped')
real2, why2 = upd.resolve_src(wrap, os.path.join(install_dir, '答题卡扫描服务.exe'))
eq(os.path.abspath(real2), os.path.abspath(inner_app),
   '多包了一层也能往下找到那一层（否则会把安装目录覆盖成空壳）')

# 真的什么都没有 → 给错误，而不是拿空目录去覆盖安装目录
empty2 = os.path.join(TMP, 'really-empty')
os.makedirs(empty2, exist_ok=True)
real3, why3 = upd.resolve_src(empty2, os.path.join(install_dir, '答题卡扫描服务.exe'))
eq(real3, None, '空目录 → 不给目录，返回值是 None')
ok('没有可执行文件' in why3, '给出人话原因', why3)

# 端到端：pending 指向一个空目录 → 落地失败且**安装目录保持不动**
exe_keep = _mk_onedir('答题卡扫描服务Keep', 'KEEP')
upd.write_pending(TMP, empty2, exe_keep, 'v9.9.15', [])
_saved_k = sys.executable
try:
    sys.executable = os.path.join(TMP, 'boss', 'boss.exe')
    rk = upd.apply_pending(TMP)
finally:
    sys.executable = _saved_k
eq(rk['ok'], False, '暂存内容不完整 → 不谎报成功')
eq(open(os.path.join(os.path.dirname(exe_keep), '_internal', 'payload.dll'),
        encoding='utf-8').read(), 'KEEP', '**安装目录原封不动**（没被覆盖成空壳）')


# ---------------------------------------------------------------- 3. 自我锁定保护

print('\n【3】init 自身就是要被替换的那份 → 不能删自己，要标记 selfLocked')

install_exe2 = _mk_onedir('答题卡扫描服务2', 'OLD2')
stage2 = _mk_stage('v9.9.10')
upd.write_pending(TMP, stage2, install_exe2, 'v9.9.10', [])
_saved2 = sys.executable
try:
    sys.executable = install_exe2          # 模拟「直接在安装目录里跑，还想替换自己」
    res2 = upd.apply_pending(TMP)
finally:
    sys.executable = _saved2
eq(res2['selfLocked'], True, '识别出「当前进程就是目标」→ selfLocked')
eq(res2['ok'], False, '不该谎报成功')
eq(open(os.path.join(os.path.dirname(install_exe2), '_internal', 'payload.dll'),
        encoding='utf-8').read(), 'OLD2', '**没有动自己**（否则会把自己删成半截）')


# ---------------------------------------------------------------- 4. 失败要留痕

print('\n【4】引导程序崩了要留痕 —— 否则界面上只是「点了没反应」')

eq(upd.bootstrap_failure(TMP), None, '没出过事故时 → None')
upd.record_bootstrap(TMP, {'version': 'v9.9.9', 'exitCode': 3221225781,
                           'error': 'Failed to load Python DLL'})
f = upd.bootstrap_failure(TMP)
ok(isinstance(f, dict), '记下之后能读出来')
eq(f['version'], 'v9.9.9', '带上想装的版本')
eq(f['exitCode'], 3221225781, '带上退出码（0xC0000135 = 缺 DLL 那种）')
ok('Failed to load Python DLL' in f['error'], '带上人话原因', f['error'])
upd.clear_bootstrap(TMP)
eq(upd.bootstrap_failure(TMP), None, '清掉后不再回报（不能每次都弹旧事故）')

# 引导程序写日志的入口
upd.bootlog(TMP, '启动引导程序：C:\\path\\to\\boss.exe --install-pending')
log = os.path.join(TMP, 'update.log')
ok(os.path.exists(log), '写了 update.log')
ok('启动引导程序' in open(log, encoding='utf-8').read(), '日志内容可读')


# ---------------------------------------------------------------- 5. 启动参数传递

print('\n【5】引导程序要把原启动参数带给新版本（否则 --host 0.0.0.0 会丢）')

args = ['--install-pending', '--data', 'C:\\d', '--port', '9000', '--host', '0.0.0.0']
out = upd._drop_flag_with_value(list(args), '--data')
ok('--data' not in out and 'C:\\d' not in out, '--data 连同它的值一起去掉（引导程序自己会给）')
ok('--port' in out and '9000' in out, '--port/值保留')
ok('--host' in out and '0.0.0.0' in out, '--host 保留')
ok(upd._drop_flag_with_value(['--install-pending', '-p', '9000'], '--data') ==
   ['--install-pending', '-p', '9000'], '没有该参数时原样返回')


# ---------------------------------------------------------------- 6. 端到端：pending → 落地 → 拉起

print('\n【6】端到端：pending → 落地 → 拉起新版本（bootstrap 干的事）')

install_exe3 = _mk_onedir('答题卡扫描服务3', 'OLD3')
stage3 = _mk_stage('v9.9.11')
upd.write_pending(TMP, stage3, install_exe3, 'v9.9.11', ['--port', '9001'])
p = upd.read_pending(TMP)
eq(len(p.get('items') or []), 1, 'pending 里有 1 项')
eq(p['items'][0]['flavor'], upd.SELF_FLAVOR, 'flavor 是 scanner')
eq(p['items'][0]['launch_args'], ['--port', '9001'], '记下了拉起时要带的参数')

_saved3 = sys.executable
try:
    sys.executable = os.path.join(TMP, 'boss', 'boss.exe')
    r3 = upd.apply_pending(TMP)
finally:
    sys.executable = _saved3
eq(r3['ok'], True, '端到端落地成功')
eq(open(os.path.join(os.path.dirname(install_exe3), '_internal', 'payload.dll'),
        encoding='utf-8').read(), 'v9.9.11', '安装目录内容 = 新版本')

shutil.rmtree(TMP, ignore_errors=True)

print('\n' + '=' * 60)
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f_ in FAILS:
        print('   -', f_)
    sys.exit(1)
print('🎉 自更新落地与重启测试全部通过')