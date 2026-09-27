# -*- coding: utf-8 -*-
"""引导程序（scanner_launcher.py 的 --install-pending 分支）的离线回归测试。

    python tests/test_bootstrap_launcher.py

**为什么单独测这个文件**：1.4.0 的「更新并重启没反应」直接出在这一段，而它此前
零覆盖 —— 因为它藏在打包目录里、又只在「服务已经退出之后」才跑，靠人工点界面
根本观察不到中间状态。这里把 `subprocess.Popen` 换成假的，就能把整条控制流
（报到 → 等旧进程退 → 落地 → 拉起）完整走一遍并逐项断言。

验证的核心行为：
  · 进来第一件事是 `mark_boot_reported()`（老服务正靠它决定要不要退出）
  · 等旧服务退出**成功之后**才动文件（不等就替换 = 撞 Windows 文件锁）
  · 落地成功 → 用**新版本 exe + 原启动参数**拉起
  · 任何一步失败 → 写 update_boot.json 事故记录（否则界面上永远只是「没反应」）
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.dirname(HERE)
REPO = os.path.dirname(SCANNER)
LAUNCHER = os.path.join(REPO, 'packaging', 'windows', 'scanner_launcher.py')

sys.path.insert(0, SCANNER)
TMP = tempfile.mkdtemp(prefix='asb-boot-test-')
os.environ['ASB_DATA'] = TMP
os.environ['ASB_DB'] = os.path.join(TMP, 'test.db')

from app import update as upd  # noqa: E402

FAILS = []
POPENS = []


def ok(cond, label, extra=''):
    print(('  ✅ ' if cond else '  ❌ ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


def eq(got, want, label):
    ok(got == want, label, f'（期望 {want}，实测 {got}）')


def load_launcher():
    """把打包目录里的启动器当模块加载（它有 __main__ 守卫，import 不会起服务）。"""
    spec = importlib.util.spec_from_file_location('asb_launcher', LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


launcher = load_launcher()


class FakePopen:
    """记下被拉起了什么，不真的执行（假 exe 跑起来只会报错，掩盖真实控制流）。"""

    def __init__(self, args, **kw):
        POPENS.append(list(args) if isinstance(args, (list, tuple)) else args)


def mk_install(name, tag):
    app = os.path.join(TMP, 'install', name)
    os.makedirs(os.path.join(app, '_internal'), exist_ok=True)
    exe = os.path.join(app, name + '.exe')
    open(exe, 'w', encoding='utf-8').close()
    with open(os.path.join(app, '_internal', 'payload.dll'), 'w', encoding='utf-8') as fh:
        fh.write(tag)
    return exe


def mk_stage(version):
    app = os.path.join(TMP, 'updates', version, 'scanner', '答题卡扫描服务-Windows-x64')
    os.makedirs(os.path.join(app, '_internal'), exist_ok=True)
    with open(os.path.join(app, '答题卡扫描服务.exe'), 'w', encoding='utf-8') as fh:
        fh.write('EXE-' + version)
    with open(os.path.join(app, '_internal', 'payload.dll'), 'w', encoding='utf-8') as fh:
        fh.write(version)
    return app


def payload_of(install_exe):
    return open(os.path.join(os.path.dirname(install_exe), '_internal', 'payload.dll'),
                encoding='utf-8').read()


def setup_case(version, name='答题卡扫描服务', args=None, pid=0):
    """造一次「服务已退出、引导程序刚被拉起」的现场。"""
    shutil.rmtree(os.path.join(TMP, 'updates'), ignore_errors=True)
    upd.clear_bootstrap(TMP)
    upd.clear_pending(TMP)
    exe = mk_install(name, 'OLD')
    stage = mk_stage(version)
    launch_args = list(args if args is not None else ['--port', '8081'])
    # 服务退出前写的东西，与 trigger_install 一致
    upd.write_boot_intent(TMP, version, os.path.join(stage, name + '.exe'),
                          install_exe=exe, launch_args=launch_args)
    upd.write_pending(TMP, stage, exe, version, launch_args)
    # 让 write_boot_intent 里的 servicePid 可控：直接改文件（pid=0 表示不等待）
    d = upd.read_boot_intent(TMP)
    d['servicePid'] = pid
    with open(upd._boot_path(TMP), 'w', encoding='utf-8') as fh:
        json.dump(d, fh)
    return exe, stage, launch_args


# ---------------------------------------------------------------- 1. 报到

print('【1】进来第一件事是「报到」—— 老服务靠这个信号才肯退出')

exe, stage, args = setup_case('v9.9.9')
eq(upd.boot_reported(TMP), False, '报到前：reportedAt 还是 0')
saved_popen = launcher.subprocess.Popen
saved_wait = upd.wait_for_pid_exit
launcher.subprocess.Popen = FakePopen
try:
    rc = launcher._bootstrap_apply_and_relaunch(TMP)
finally:
    launcher.subprocess.Popen = saved_popen
eq(rc, 0, '整条流程返回 0（成功）')
eq(upd.boot_reported(TMP), True, '**报到标记被回填了**（否则老服务会一直等、谁都不干活）')


# ---------------------------------------------------------------- 2. 落地 + 拉起

print('\n【2】落地 + 拉起：真的换了文件，而且拉的是新版本')

eq(payload_of(exe), 'v9.9.9', '**安装目录里的内容换成了新版本**')
ok(os.path.exists(os.path.join(os.path.dirname(exe), '_internal', 'payload.dll')),
   '_internal 一起换掉了（裸 exe 引导程序做不到的事）')
eq(os.listdir(os.path.dirname(exe) + '.bak') is not None, True,
   '旧版本留在 .bak 备份里（万一新版起不来还能人工回滚）')
ok(len(POPENS) == 1, f'拉起了一次新版本（实测 {len(POPENS)} 次）')
eq(POPENS[0][0], exe, '拉起的是**安装目录**里的 exe（不是暂存目录里的）')
eq(POPENS[0][1:], ['--port', '8081'], '原启动参数原样带过去了（--host/--data 不会丢）')


# ---------------------------------------------------------------- 3. 等旧进程退出

print('\n【3】等旧服务退出 —— 不等就替换会撞 Windows 文件锁')

exe2, stage2, _ = setup_case('v9.9.10', pid=424242)
waited = {}
saved_popen = launcher.subprocess.Popen
launcher.subprocess.Popen = FakePopen
saved_wait = upd.wait_for_pid_exit


def fake_wait(pid, timeout=None):
    waited['pid'] = pid
    waited['timeout'] = timeout
    return True


upd.wait_for_pid_exit = fake_wait
try:
    rc = launcher._bootstrap_apply_and_relaunch(TMP)
finally:
    upd.wait_for_pid_exit = saved_wait
    launcher.subprocess.Popen = saved_popen
eq(rc, 0, '等待成功 → 继续落地')
eq(waited.get('pid'), 424242, '把 servicePid 传给了等待函数')
ok(waited.get('timeout') and waited['timeout'] > 0, '带上了超时（不会无限等）',
   str(waited.get('timeout')))
eq(payload_of(exe2), 'v9.9.10', '等到了才替换 —— 文件是新的')

# 等服务超时 → 必须放弃、留痕，不能硬着头皮替换
exe3, stage3, _ = setup_case('v9.9.11', pid=424243)
saved_popen = launcher.subprocess.Popen
launcher.subprocess.Popen = FakePopen


def wait_timeout(pid, timeout=None):
    return False


upd.wait_for_pid_exit = wait_timeout
try:
    rc = launcher._bootstrap_apply_and_relaunch(TMP)
finally:
    upd.wait_for_pid_exit = saved_wait
    launcher.subprocess.Popen = saved_popen
eq(rc, 1, '等不到旧服务退出 → 返回失败码')
eq(payload_of(exe3), 'OLD', '**没有硬替换**（撞锁只会弄坏安装目录）')
f = upd.bootstrap_failure(TMP)
ok(isinstance(f, dict) and '没有退出' in (f.get('error') or ''),
   '记下了「旧服务没退出」的事故', (f or {}).get('error'))
upd.clear_bootstrap(TMP)


# ---------------------------------------------------------------- 4. 失败要留痕

print('\n【4】任何一步失败都要留下事故记录（否则界面只是「点了没反应」）')

# (a) 暂存目录被清掉 → 落地失败
exe4, stage4, _ = setup_case('v9.9.12', pid=0)
shutil.rmtree(stage4)
saved_popen = launcher.subprocess.Popen
launcher.subprocess.Popen = FakePopen
upd.wait_for_pid_exit = fake_wait
try:
    rc = launcher._bootstrap_apply_and_relaunch(TMP)
finally:
    launcher.subprocess.Popen = saved_popen
    upd.wait_for_pid_exit = saved_wait
eq(rc, 1, '暂存目录没了 → 返回失败码')
f = upd.bootstrap_failure(TMP)
ok(isinstance(f, dict), '留下了事故记录（下次开服务会显示给用户）')
ok('暂存目录' in (f.get('error') or ''), '原因说得清', (f or {}).get('error'))
upd.clear_bootstrap(TMP)

# (b) 拉起失败 → 也要留痕（文件已经换了，但服务没起来）
exe5, stage5, _ = setup_case('v9.9.13', pid=0)
saved_popen = launcher.subprocess.Popen


def popen_boom(*a, **kw):
    raise OSError('Access is denied')


launcher.subprocess.Popen = popen_boom
upd.wait_for_pid_exit = fake_wait
try:
    rc = launcher._bootstrap_apply_and_relaunch(TMP)
finally:
    launcher.subprocess.Popen = saved_popen
    upd.wait_for_pid_exit = saved_wait
eq(rc, 1, '拉起失败 → 返回失败码')
eq(payload_of(exe5), 'v9.9.13', '但文件已经落地了（下次双击启动就是新版）')
f = upd.bootstrap_failure(TMP)
ok('拉起失败' in (f.get('error') or ''), '记的是「落地成功但拉起失败」', (f or {}).get('error'))
upd.clear_bootstrap(TMP)

# (c) 没有 boot 记录 → 静默退出，不做事（避免误伤正常启动）
shutil.rmtree(os.path.join(TMP, 'install'), ignore_errors=True)
eq(launcher._bootstrap_apply_and_relaunch(TMP), 0, '没有 update_boot.json → 直接返回 0')


# ---------------------------------------------------------------- 5. 日志

print('\n【5】update.log —— 事后能不能查明白发生了什么')

log = os.path.join(TMP, 'update.log')
txt = open(log, encoding='utf-8').read() if os.path.exists(log) else ''
ok(os.path.exists(log), '日志文件存在')
for kw in ('引导程序已启动', '等待旧服务', '落地更新成功', '已拉起新版本'):
    ok(kw in txt, f'日志里有「{kw}」')

shutil.rmtree(TMP, ignore_errors=True)

print('\n' + '=' * 60)
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f_ in FAILS:
        print('   -', f_)
    sys.exit(1)
print('🎉 引导程序（落地+重启）测试全部通过')