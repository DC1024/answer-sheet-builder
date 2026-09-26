# 答题卡扫描识别服务：上传阅卷模板 + 扫描图 → 识别选择题填涂 → 汇总统计
# 纯 OpenCV，无模型下载，可完全离线运行。
#
# 两条识别入口共用同一条识别路径（_recognize_bytes）：
#   POST /api/scan    单张 / 少量图片，来一批识别一批，结果累积
#   POST /api/batch   一个班的扫描件（zip 或整个文件夹）+ 名单，按考号归组、多页合并、跟名单匹配
#
# ---- 2026-09-25 起：不再有进程内状态 ----
#
# 原来所有东西都放在一个全局 `STATE` 字典里，后果是：容器一重建、或改一行代码触发重启，
# 整个班的结果连同老师刚补录的姓名一起没了。现在全部落 SQLite（store.py），
# 每次请求按 `exam_id` 现场读出来。
#
# 「不再有内存态」这件事不只是持久化，它还顺手解决了一个并发的坑：
# 两个老师各看各的考试时，同一个 STATE 会被来回覆盖 —— 我这边切个考试，
# 你那边再点一下统计就会算到我的班上。现在每次请求都从库里按 exam_id 取，串不了。
import importlib.util
import json
import os
import time
import uuid

import numpy as np
import cv2
from flask import (Flask, jsonify, request, send_from_directory, Response,
                   redirect, g)

from . import __version__ as APP_VERSION
from . import omr
from . import batch as bt
from . import stats as st
from . import scoring as scor
from . import store as store_mod
from . import auth as auth_mod
from . import settings as settings_mod
from . import update as upd
from . import fixes as fixes_mod

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
# 数据目录（库 + 校对图）。容器里默认落到 /srv/data（compose 的 bind mount）；
# 但 Windows 免安装版冻结成 exe 后 `__file__` 在 PyInstaller 的临时解包目录里，
# 默认值会变成「每次启动都是空的」—— 所以启动器在 import 本模块之前用
# ASB_DATA 把它指到 %LOCALAPPDATA%\asb-scanner\data。docker 部署不受影响。
DATA = os.environ.get('ASB_DATA') or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
os.makedirs(DATA, exist_ok=True)

# 库文件跟着 data/ 走 —— 它是 compose 的 bind mount，容器重建也留得住
DB_PATH = os.environ.get('ASB_DB') or os.path.join(DATA, 'asb.db')
STORE = store_mod.Store(DB_PATH)
AUTH = auth_mod.Auth(STORE)
# 本机偏好（自动检查更新等），跟库放一起备份
SETTINGS = settings_mod.Settings(os.path.join(DATA, 'settings.json'))

app = Flask(__name__, static_folder=STATIC, static_url_path='')
# 一个班 50 人 × 2 面 × 1MB 很容易过 100MB —— 给足余量（反正在内网跑）
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024

COOKIE_SECURE = os.environ.get('ASB_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes')


class ApiError(Exception):
    """带状态码的业务错误，直接吐给前端。"""

    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- 识别

def _decode(data):
    buf = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise omr.OmrError('无法解码图片（仅支持 PNG / JPG 等常见格式）')
    return img


# ---------------------------------------------------------------- 手写 CNN 懒加载
#
# 权重（hwletter_cnn.pt）和 torch 都不保证在容器里存在 —— 没权重 / 没 torch 时，
# 整条手写识别退回纯 OpenCV（decode_write(cnn_model=None)），绝不因加载失败而崩。
# 所以这里只在**第一次**被请求时尝试加载一次，失败就永远返回 None，并记一条日志。
_CNN_MODEL = None
_CNN_TRIED = False


def _get_cnn_model():
    """返回已加载的 CNN 模型，或 None（无权重/无 torch/加载失败）。线程安全由 GIL 兜底。"""
    global _CNN_MODEL, _CNN_TRIED
    if _CNN_TRIED:
        return _CNN_MODEL
    _CNN_TRIED = True
    try:
        from . import cnn_letter
        # 权重路径可被环境变量顶掉：Windows 免安装版用 ASB_CNN_MODEL 指到
        # 一个不存在的路径即可显式关掉 CNN（省内存），无需卸载 torch。
        path = os.environ.get('ASB_CNN_MODEL') or cnn_letter.DEFAULT_MODEL
        _CNN_MODEL = cnn_letter.load_model(path)
        app.logger.info('手写 CNN 已加载：%s', path)
    except Exception as e:  # noqa: BLE001 —— 任何失败都退回 OpenCV，不该让请求崩
        _CNN_MODEL = None
        app.logger.warning('手写 CNN 加载失败，退回纯 OpenCV：%s', e)
    return _CNN_MODEL


def _cnn_status():
    """手写 CNN 到底能不能用 —— 只做**静态**判断，不真的加载模型。

    `/api/health` 是 docker 健康检查的目标（每几十秒打一次），而加载一次 torch 要 1~2 秒，
    所以这里只回答「权重在不在 + torch 找不找得到」，够用且便宜；真正加载仍然只在第一次
    识别时懒执行（见 `_get_cnn_model`）。

    存在的意义：权重和 torch 都是**可选件**，缺了服务照样起得来 —— 于是「服务活着」
    并不能证明「打包时把 CNN 装对了」。免安装版就是靠这个字段自证的。
    """
    from . import cnn_letter
    path = os.environ.get('ASB_CNN_MODEL') or cnn_letter.DEFAULT_MODEL
    try:
        have_torch = importlib.util.find_spec('torch') is not None
    except Exception:  # noqa: BLE001 —— 冻结环境里 find_spec 也可能抛
        have_torch = False
    have_weights = bool(path) and os.path.isfile(path)
    return {'weights': have_weights, 'torch': have_torch,
            'ready': have_weights and have_torch}


def _recognize_bytes(data, name, tpl, page_idx=0, px_per_mm=8.0, fill_min=0.5, gap=0.15,
                     cnn_model=None):
    """识别一张图 → (结果字典, answers)。识别失败时 answers 为 None。

    单张扫描和批量上传都走这里 —— 免得两条路各修一次、还修得不一样。
    cnn_model: 手写 A-D CNN（传 None 则 decode_write 退化为纯 OpenCV）。

    结果里带 `engine`（这份卷子用的哪套方案：rule / cnn / mixed）+ 每题 `by`
    （这一题谁定的音），answers 里也各存一份 —— 老师要据此对比两套方案的误判率，
    所以「方案」必须跟着结果一起落库，不能只活在前端的一次响应里。
    """
    try:
        img = _decode(data)
        r = omr.recognize(img, tpl, page_idx=page_idx, px_per_mm=px_per_mm,
                          fill_min=fill_min, gap=gap, cnn_model=cnn_model)
        rid = uuid.uuid4().hex[:12]
        png = r.pop('overlayPng', None)
        saved = _save_overlay(rid, png) if png else False
        answers = {q['no']: {'answer': q['answer'], 'flag': q['flag'], 'best': q['best'],
                             'second': q['second'], 'ratios': q['ratios'], 'inks': q['inks'],
                             'by': q.get('by'), 'votes': q.get('votes') or {}}
                   for q in r['questions']}
        if r.get('sid'):
            # 逐位坐标（x/y/w/h）是给 draw_overlay 用的，没必要发给浏览器
            r['sid'] = {k: r['sid'].get(k) for k in ('text', 'digits', 'ok', 'filled', 'flags')}
        r.update({'id': rid, 'name': name, 'ok': True, 'overlay': saved})
        if png and not saved:
            # 校对图存不下来不该让整份结果作废 —— 答案已经识别出来了
            r['overlayError'] = '校对图无法写入 data/（检查挂载目录是否存在且可写）'
        return r, answers
    except Exception as e:
        return {'ok': False, 'name': name, 'error': str(e)}, None


def _save_overlay(rid, png):
    """写校对图。目录可能因挂载变动而消失，所以每次写入前都重新确认一次。"""
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(os.path.join(DATA, rid + '.png'), 'wb') as fh:
            fh.write(png)
        return True
    except OSError:
        return False


def _params():
    """单张 / 批量共用的识别参数。"""
    page_idx = int(request.form.get('page') or 0)
    px_per_mm = float(request.form.get('pxPerMm') or request.form.get('dpi') or 8.0)
    fill_min = float(request.form.get('fillMin') or 0.5)
    gap = float(request.form.get('gap') or 0.15)
    return page_idx, px_per_mm, fill_min, gap


def _page_guard(tpl, page_idx):
    """越界的页序号必须报错，不能放过去。

    omr._template_quad() 会把越界页序号夹到最后一页 —— 对「多传了一页」的卷子，
    结果是拿错的模板面去采样，答案看着正常但是错的。这是阅卷工具里最坏的失败方式，
    所以在入口就把话说明白。
    """
    n = len(tpl['pages'])
    if page_idx >= n:
        raise ApiError(f'页序号 {page_idx} 超出模板范围（模板共 {n} 面）——'
                       f'请检查文件名里的页序提示，或重新导出正确的模板')


# ---------------------------------------------------------------- 上下文：哪个考试

def _req_exam_id():
    """本次请求针对哪个考试（显式给的最优先）。"""
    v = request.form.get('exam_id') or request.args.get('exam_id')
    if v in (None, ''):
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            v = body.get('exam_id')
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        raise ApiError('exam_id 不是数字')


def _exam(create=True):
    """取当前考试。

    显式 exam_id > 服务端记着的「当前考试」 > 最近更新过的 > 现场建一个。
    最后那条是为了让「刚部署、什么都没有」也能直接用：上传模板时自然就有了第一个考试。

    可见性：**所有登录用户都能看到所有考试**（一个学校就一个教研室，按人隔离反而是负担）。
    归属只用来管「谁能删」。这个取舍写在 README 里。
    """
    eid = _req_exam_id()
    if eid is not None:
        e = STORE.exam(eid)
        if not e:
            raise ApiError('这个考试不存在（可能已被别人删掉），刷新一下页面', 404)
        return e
    cid = STORE.get_meta('current_exam')
    if cid:
        e = STORE.exam(cid)
        if e:
            return e
    rows = STORE.exams()
    if rows:
        return STORE.exam(rows[0]['id'])
    if not create:
        raise ApiError('还没有任何考试', 404)
    e = STORE.create_exam('默认考试', owner_id=g.user['id'])
    STORE.set_meta('current_exam', e['id'])
    return e


def _exam_template(exam, required=True):
    tpl = exam.get('templateJson')
    if not tpl and required:
        raise ApiError('请先上传「阅卷模板」')
    return tpl


def _roster_info(exam):
    return {'count': len(exam['roster']), 'columns': exam['rosterCols'],
            'source': exam['roster_source']}


def _key_text(key):
    """标准答案转回可编辑文本（`1A 2B 3C`）—— 老师刷新页面后要能看见自己输过什么。"""
    if not key:
        return ''
    # 题号按 int 排（题号正常情况下就是 int；万一有怪题号排到最后，别让整页崩掉）
    order = sorted(key, key=lambda x: (0, x) if isinstance(x, int) else (1, str(x)))
    return ' '.join(f'{k}{key[k]}' for k in order)


# ---------------------------------------------------------------- 结果集

def _label(stu):
    """「2026010234 张伟明」—— 解析不出考号时退回文件名。"""
    parts = [str(stu.get('sid') or ''), stu.get('name') or '']
    txt = ' '.join(p for p in parts if p).strip()
    return txt or (stu.get('source') or '未命名')


def _student_sheet(stu, applied=False):
    """学生记录 → 统计/导出要的「一份卷子」。现场算，不缓存 —— 补录改名立刻生效。

    applied=False（默认）时 answers 是**人工修正之后**的生效答案 —— 统计、判分、
    导出要的都该是这个，否则老师改完答案分数不变（这一条踩过：改完答案刷新回来还是
    原分，因为下游还在读机器原读数）。
    需要「机器原读」的场合（误判率统计）传 applied=True，拿未经合并的那份。
    """
    fixes = stu.get('fixes') or {}
    answers = stu.get('answers') or {}
    if not applied and fixes:
        answers, _ = fixes_mod.apply(answers, fixes)
    return {'id': 'stu-' + str(stu.get('sid')), 'name': _label(stu),
            'answers': answers, 'sid': str(stu.get('sid')),
            'stu': stu.get('name') or '', 'cls': stu.get('cls') or '',
            'source': stu.get('source') or '',
            # 原始机器读数一直带着 —— 误判率统计要「机器读到啥 vs 老师改成啥」的配对，
            # 只在需要时（exam_accuracy）取用，平时不参与判分。
            'machineAnswers': stu.get('answers') or {},
            'fixes': fixes}


def _sheets(exam, ids=None, applied=True):
    """取结果集。默认只取这个考试「最近一次识别」那一批。

    applied=True（默认）→ answers 是人工修正后**生效**的答案。
    applied=False → 保留机器原读（误判率统计用）。

    ⚠️ `_student_sheet` 的 `applied` 语义正好相反（它 False=合并、True=原读），
    所以传过去要取反。早期这里直接透传 `applied`，导致 stats/export 走默认
    applied=True 时读到的还是机器原读 —— 老师改完答案，统计和导出却不变。
    """
    if ids is None:
        ids = list(exam['activeIds'] or [])
    if not ids:
        ids = ['stu-' + str(s['sid']) for s in STORE.students(exam['id'])] + \
            [s['id'] for s in STORE.scans(exam['id'])]
    want_stu = [str(i)[4:] for i in ids if str(i).startswith('stu-')]
    want_scan = [str(i) for i in ids if not str(i).startswith('stu-')]
    found = {}
    for s in STORE.students(exam['id'], sids=want_stu):
        found['stu-' + str(s['sid'])] = _student_sheet(s, applied=not applied)
    for s in STORE.scans(exam['id'], rids=want_scan):
        if applied and s.get('fixes'):
            s = dict(s)
            s['machineAnswers'] = s.get('answers') or {}
            s['answers'], _ = fixes_mod.apply(s.get('answers') or {}, s['fixes'])
        found[s['id']] = s
    return [found[i] for i in ids if i in found]          # 保持 ids 的顺序


# 发给浏览器的每题字段。`ratios` / `inks` 是 matplotlib 之外的 numpy 标量，
# 直接 jsonify 也可能出问题（虽然大多能过），所以统一走白名单，顺带剪掉体积。
_ANS_FIELDS = ('answer', 'flag', 'by', 'best', 'second', 'machine', 'machineFlag',
               'machineBy', 'fixNote', 'fixBy', 'fixAt', 'votes', 'cnn')


def _ans_view(a):
    """一条答案 → 前端要的瘦身版（只留白名单字段，numpy 标量转 Python 标量）。"""
    if not isinstance(a, dict):
        return {'answer': None, 'flag': None}
    out = {}
    for k in _ANS_FIELDS:
        if k in a:
            out[k] = a[k]
    return out


def _qnos(exam, sheets):
    """题号全集：模板是权威（含学生都没填的题），没有模板才退回结果里出现过的题号。"""
    tpl = exam.get('templateJson')
    if tpl:
        return sorted({q['no'] for p in tpl['pages'] for q in p.get('questions', [])})
    return sorted({q for s in sheets for q in s['answers']})


# ---------------------------------------------------------------- 名单 / 补录

def _incoming_overrides():
    """这次请求带的补录数据。两种传法都要认：跟文件一起的表单字段，或 JSON 体。"""
    raw = request.form.get('overrides')
    if raw:
        try:
            d = json.loads(raw)
        except ValueError:
            return {}
        return d if isinstance(d, dict) else {}
    body = request.get_json(silent=True)
    d = body.get('overrides') if isinstance(body, dict) else None
    return d if isinstance(d, dict) else {}


def _merge_overrides(exam, incoming):
    """把这次带的补录并进库里那份，返回合并结果。

    补录**必须落库**：老师填完姓名一刷新就没了，正是这次改造要解决的问题。
    用合并而不是替换 —— 前端只带自己记得的那几个，替换会把别处录的冲掉。
    """
    cur = dict(exam['overrides'] or {})
    for sid, v in (incoming or {}).items():
        if not isinstance(v, dict):
            continue
        keep = {k: str(v.get(k)).strip() for k in ('name', 'cls') if str(v.get(k) or '').strip()}
        if keep:
            cur.setdefault(str(sid), {}).update(keep)
    return cur


def _load_roster(exam, explicit, embedded):
    """名单来源：显式上传的 > zip 里自带的；都没有就沿用这个考试已有的那份。

    只有拿到新名单时才覆盖 —— 这样「先单独导名单、再传扫描件」的用法
    不会因为第二次没带名单文件而丢掉名单。
    """
    if explicit is not None and explicit.filename:
        try:
            roster, cols = bt.parse_roster(bt._read_text(explicit.read()))
        except bt.BatchError as e:
            raise ApiError('名单解析失败：' + str(e))
        STORE.set_roster(exam['id'], roster, cols, explicit.filename)
    else:
        found = bt.find_roster(embedded)
        if found:
            roster, cols, src = found
            STORE.set_roster(exam['id'], roster, cols, src)
    return STORE.exam(exam['id'])


def _match(exam, overrides, save=False):
    """套名单 → (students, warnings)。save=True 时把结果写回库。"""
    students = STORE.students(exam['id'])
    students, warnings = bt.match(students, exam['roster'], overrides)
    if save:
        # keep_manual：重新套名单只是改姓名/班级标注，绝不能顺手清掉逐题修正与复核标记
        STORE.save_students(exam['id'], students, keep_manual=True)
        STORE.set_overrides(exam['id'], overrides)
    return students, warnings


def _students_view(exam, applied=True):
    """当前考试的学生视图。

    读的时候**现场重套一次名单**，而不是返回库里存着的 name/cls ——
    刚改完名单、或另一个人补录了一个名字，这里是立刻可见的，
    也不会出现「库里存的 matched 标记跟名单对不上」这种陈旧数据。

    applied=True（默认）时再叠一层**人工修正**：answers 变成老师改过之后的生效答案。
    下游的判分 / 成绩分析 / 导出全都读这个视图，所以改一次答案就处处生效。

    ⚠️ 合并只发生在**返回的这份拷贝**上，绝不回写 —— 写回会把 `answers` 里的
    机器原读覆盖掉，而误判率统计正是靠「机器原读 vs 人工修正」的配对算出来的。
    写库的路径（_match(save=True)）用的是未合并的 students。
    """
    if not STORE.students(exam['id']):
        return [], []
    students, warnings = _match(exam, exam['overrides'])
    if not applied:
        return students, warnings
    out = []
    for s in students:
        fixes = s.get('fixes') or {}
        if not fixes:
            out.append(s)
            continue
        s = dict(s)
        s['machineAnswers'] = s.get('answers') or {}
        s['answers'], changed = fixes_mod.apply(s.get('answers') or {}, fixes)
        s['fixedQnos'] = sorted(changed)
        out.append(s)
    return out, warnings


# ---------------------------------------------------------------- 鉴权闸门

# 这几个接口不需要登录：探活、登录本身、以及登录页要问的「我是谁 / 初始化过没有」
PUBLIC_API = {'/api/health', '/api/login', '/api/setup', '/api/me'}


@app.before_request
def _gate():
    """所有 /api/* 都要登录（白名单除外）。

    放在 before_request 而不是逐个路由加装饰器：**默认拒绝**才安全，
    以后新加接口忘了加装饰器也不会漏在外面。写操作的**角色**要求仍然逐个标（见各路由）。
    """
    p = request.path
    if not p.startswith('/api/') or p in PUBLIC_API:
        return None
    u = AUTH.current()
    if not u:
        return jsonify({'error': '未登录', 'needLogin': True}), 401
    g.user = u
    return None


def _err(msg, code=400):
    """把 ApiError / BatchError / AuthError 统一成 JSON。"""
    return jsonify({'error': str(msg)}), code


# ---------------------------------------------------------------- 路由：公开

@app.get('/')
def index():
    if AUTH.need_setup() or not AUTH.current():
        return redirect('/login')
    return send_from_directory(STATIC, 'index.html')


@app.get('/login')
def login_page():
    return send_from_directory(STATIC, 'login.html')


@app.get('/api/health')
def health():
    """探活 + 初始化状态。docker healthcheck 也打这个（**不能要求登录**）。

    带 `cnn` 是为了让**打包产物自己**证明手写 CNN 装进去了没有 —— 权重和 torch 都是
    可选件，服务无论如何都能起来，所以「起得来」不等于「装对了」。

    `engine` 是「本服务当前**实际生效**的识别方案」，与 `cnn.ready` 的区别在于：
    ready 只说「装了没有」，engine 说「跑的时候会不会真的用上」。两者不一致
    （如被 ASB_CNN_MODEL 指到空路径）时，engine 才是老师该看的那一个。
    """
    cnn = _cnn_status()
    return jsonify({'ok': True, 'needSetup': AUTH.need_setup(),
                    'schema': STORE.schema_version(), 'version': APP_VERSION,
                    'cnn': cnn, 'engine': _engine_status(cnn)})


def _engine_status(cnn=None):
    """当前生效的识别方案（给界面显示 + 老师对比误判率时对齐口径）。"""
    cnn = cnn or _cnn_status()
    return {
        'write': omr.ENGINE_CNN if cnn['ready'] else omr.ENGINE_RULE,
        'writeZh': omr.ENGINE_ZH[omr.ENGINE_CNN if cnn['ready'] else omr.ENGINE_RULE],
        'choice': omr.ENGINE_RULE,
        'choiceZh': omr.ENGINE_ZH[omr.ENGINE_RULE],
        'cnnNote': (None if cnn['ready'] else
                    '手写 A-D 走结构特征规则；装好 torch 与权重后会自动升级为 CNN 交叉验证'),
    }


# ---------------------------------------------------------------- 设置 / 检查更新

@app.get('/api/settings')
def get_settings():
    """本机设置 + 版本信息。界面上的「设置」卡片就靠它渲染。"""
    return jsonify({
        'ok': True,
        'version': APP_VERSION,
        'settings': SETTINGS.get(),
        'checkInterval': settings_mod.CHECK_INTERVAL,
        'releasesUrl': upd.RELEASES_URL,
    })


@app.post('/api/settings')
@AUTH.require(*auth_mod.CAN_WRITE)
def set_settings():
    """改本机设置（目前只有「自动检查更新」这一个开关）。"""
    body = request.get_json(silent=True) or {}
    try:
        s = SETTINGS.patch(body)
    except ValueError as e:
        return _err(e)
    return jsonify({'ok': True, 'settings': s})


@app.get('/api/update')
def check_update():
    """查有没有新版本。`?force=1` 强制重新查，否则 6 小时内直接回缓存。

    不抛异常：连不上 GitHub（内网很常见）时回 `ok:false` + 一句人话，
    前端显示「暂时查不到」而不是报错。
    """
    force = (request.args.get('force') or '').lower() in ('1', 'true', 'yes')
    cur = SETTINGS.get()
    cached = cur.get('last_result')
    fresh = (time.time() - float(cur.get('last_check') or 0)) < settings_mod.CHECK_INTERVAL
    if not force and isinstance(cached, dict) and cached.get('ok') and fresh:
        return jsonify(dict(cached, cached=True, checkedAt=int(cur.get('last_check') or 0)))

    res = upd.check(APP_VERSION)
    if res.get('ok'):
        # 只缓存成功的查询 —— 断网时的失败结果不该把用户锁在「查不到」里 6 小时
        SETTINGS.patch({'last_check': int(time.time()), 'last_result': res})
    return jsonify(dict(res, cached=False, checkedAt=int(time.time()) if res.get('ok') else 0))


@app.get('/api/me')
def me():
    """当前登录身份。登录页靠它判断「要不要引导创建管理员」。"""
    return jsonify({'user': auth_mod.user_json(AUTH.current()),
                    'needSetup': AUTH.need_setup()})


@app.post('/api/setup')
def setup():
    """创建第一个管理员。只在库里没有任何用户时可用。"""
    body = request.get_json(silent=True) or {}
    try:
        u = AUTH.setup(body.get('username') or request.form.get('username'),
                       body.get('password') or request.form.get('password'),
                       body.get('display') or '')
    except auth_mod.AuthError as e:
        return _err(e, e.code)
    except store_mod.StoreError as e:
        return _err(e)
    _, token = AUTH.login(u['username'], body.get('password') or request.form.get('password'))
    return auth_mod.set_cookie(jsonify({'ok': True, 'user': auth_mod.user_json(u)}),
                               token, COOKIE_SECURE)


@app.post('/api/login')
def login():
    body = request.get_json(silent=True) or {}
    try:
        u, token = AUTH.login(body.get('username') or request.form.get('username'),
                              body.get('password') or request.form.get('password'))
    except auth_mod.AuthError as e:
        return _err(e, e.code)
    return auth_mod.set_cookie(jsonify({'ok': True, 'user': auth_mod.user_json(u)}),
                               token, COOKIE_SECURE)


@app.post('/api/logout')
def logout():
    """退出登录。服务端会话**真的**被删掉 —— 不是只把 cookie 清掉。"""
    AUTH.logout(request.cookies.get(auth_mod.COOKIE))
    return auth_mod.clear_cookie(jsonify({'ok': True}))


# ---------------------------------------------------------------- 路由：考试

@app.get('/api/exams')
def list_exams():
    rows = STORE.exams()
    return jsonify({'exams': rows, 'current': (_exam(create=False)['id']
                                               if rows else None)})


@app.get('/api/exam')
def get_exam():
    exam = _exam()
    return jsonify(_exam_view(exam))


def _exam_view(exam):
    return {
        'id': exam['id'], 'name': exam['name'], 'ownerId': exam['owner_id'],
        'createdAt': exam['created_at'], 'updatedAt': exam['updated_at'],
        'template': exam['tplSummary'],
        'hasTemplate': bool(exam['templateJson']),
        'roster': _roster_info(exam),
        'answerKey': _key_text(exam['answerKey']),
        'activeIds': exam['activeIds'], 'activeKind': exam['active_kind'],
        'studentCount': len(STORE.students(exam['id'])),
        'canDelete': g.user['role'] == 'admin' or exam['owner_id'] == g.user['id'],
    }


@app.post('/api/exams')
@AUTH.require(*auth_mod.CAN_WRITE)
def create_exam():
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or request.form.get('name') or '').strip()
    if not name:
        return _err('给这个考试起个名字')
    exam = STORE.create_exam(name, owner_id=g.user['id'])
    STORE.set_meta('current_exam', exam['id'])
    return jsonify({'ok': True, 'exam': _exam_view(exam)})


@app.post('/api/exam/select')
def select_exam():
    """切到某个考试。记在服务端只是为了「浏览器第一次打开时知道看哪个」——
    之后前端一直显式带 exam_id，两个人各看各的不会互相串。"""
    eid = _req_exam_id()
    if eid is None:
        return _err('没给 exam_id')
    exam = STORE.exam(eid)
    if not exam:
        return _err('这个考试不存在', 404)
    STORE.set_meta('current_exam', eid)
    return jsonify({'ok': True, 'exam': _exam_view(exam)})


@app.post('/api/exam/rename')
@AUTH.require(*auth_mod.CAN_WRITE)
def rename_exam():
    exam = _exam()
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or request.form.get('name') or '').strip()
    if not name:
        return _err('名字不能为空')
    STORE.rename_exam(exam['id'], name)
    return jsonify({'ok': True, 'exam': _exam_view(STORE.exam(exam['id']))})


@app.post('/api/exam/delete')
@AUTH.require(*auth_mod.CAN_WRITE)
def delete_exam():
    exam = _exam()
    if g.user['role'] != 'admin' and exam['owner_id'] != g.user['id']:
        return _err('只有管理员或这个考试的创建者能删', 403)
    STORE.delete_exam(exam['id'])
    if STORE.get_meta('current_exam') == exam['id']:
        STORE.set_meta('current_exam', None)
    return jsonify({'ok': True})


@app.post('/api/answer-key')
@AUTH.require(*auth_mod.CAN_WRITE)
def save_answer_key():
    """把标准答案存到考试上。老师输了 20 个答案，刷新一次就没了是不能接受的。"""
    exam = _exam()
    body = request.get_json(silent=True) or {}
    text = body.get('key') if 'key' in body else request.form.get('key', '')
    key = st.parse_key(text or '')
    STORE.set_answer_key(exam['id'], key)
    return jsonify({'ok': True, 'answerKey': _key_text(key), 'count': len(key)})


# ---------------------------------------------------------------- 路由：模板

@app.post('/api/template')
@AUTH.require(*auth_mod.CAN_WRITE)
def upload_template():
    exam = _exam()
    f = request.files.get('file')
    if not f:
        return _err('没有上传文件')
    try:
        tpl = omr.load_template(f.read().decode('utf-8'))
    except Exception as e:
        return _err(str(e))
    summary = omr.template_summary(tpl)
    # 只有模板**真的换了**才清空已识别的结果。老师手滑重新传一遍同一份模板，
    # 不该把刚扫完的一个班清掉。
    old = exam['templateJson']
    if old is not None and _canonical(old) != _canonical(tpl):
        STORE.save_students(exam['id'], [])
        STORE.clear_scans(exam['id'])
        STORE.set_active(exam['id'], None, [])
    STORE.set_template(exam['id'], tpl, summary)
    return jsonify({'ok': True, 'summary': summary, 'exam': _exam_view(STORE.exam(exam['id']))})


def _canonical(tpl):
    return json.dumps(tpl, sort_keys=True, ensure_ascii=False)


@app.get('/api/template')
def get_template():
    exam = _exam()
    if not exam['tplSummary']:
        return jsonify({'template': None})
    return jsonify({'template': exam['tplSummary']})


# ---------------------------------------------------------------- 路由：识别

def _batch_engine(students):
    """整批结果的方案汇总：把每个学生的逐题 `by` 归并成一个口径。

    一份班里可能有一部分学生的手写题走了 CNN、选择题走结构规则 —— 所以给的是
    **逐题计数**（byCount），不是一个笼统的「全班用了 X」。
    """
    counts = {}
    for s in students or []:
        for q in (s.get('pages') or []):
            for item in (q.get('questions') or []):
                b = item.get('by')
                if b:
                    counts[b] = counts.get(b, 0) + 1
    if not counts:
        return {'engine': omr.ENGINE_RULE, 'byCount': {},
                'engineZh': omr.ENGINE_ZH[omr.ENGINE_RULE]}
    keys = set(counts)
    if keys == {omr.ENGINE_CNN}:
        eng = omr.ENGINE_CNN
    elif keys == {omr.ENGINE_RULE}:
        eng = omr.ENGINE_RULE
    elif keys == {'both'}:
        eng = 'both'
    else:
        eng = 'mixed'
    zh = {'rule': omr.ENGINE_ZH[omr.ENGINE_RULE], 'cnn': omr.ENGINE_ZH[omr.ENGINE_CNN],
          'both': '两路均未定音（需人工判）',
          'mixed': '混合（选择题走结构规则，手写题走 CNN）'}[eng]
    return {'engine': eng, 'engineZh': zh, 'byCount': counts}


@app.post('/api/scan')
@AUTH.require(*auth_mod.CAN_WRITE)
def scan():
    exam = _exam()
    tpl = _exam_template(exam)
    files = request.files.getlist('files') or ([request.files['file']] if 'file' in request.files else [])
    if not files:
        return _err('没有上传扫描图')
    page_idx, px_per_mm, fill_min, gap = _params()
    _page_guard(tpl, page_idx)

    cnn_model = _get_cnn_model()   # 第一次请求时尝试加载一次，失败退回 OpenCV
    out, saved = [], []
    for f in files:
        r, answers = _recognize_bytes(f.read(), f.filename, tpl,
                                      page_idx, px_per_mm, fill_min, gap, cnn_model)
        if answers is not None:
            saved.append((r['id'], f.filename, answers, None, None, None, f.filename))
        out.append(r)
    if saved:
        STORE.add_scans(exam['id'], saved)
        STORE.set_active(exam['id'], 'scan', [s[0] for s in saved])
    return jsonify({'results': out})


@app.post('/api/batch')
@AUTH.require(*auth_mod.CAN_WRITE)
def batch_api():
    """一次一个班：zip / 整个文件夹 / 一堆散图 + 可选名单。"""
    exam = _exam()
    tpl = _exam_template(exam)

    files = request.files.getlist('files')
    if not files:
        return _err('没有上传扫描件（zip 压缩包 / 整张图片 / 整个文件夹都行）')
    page_idx, px_per_mm, fill_min, gap = _params()
    cnn_model = _get_cnn_model()   # 手写 CNN：第一次请求时加载一次，失败退回 OpenCV

    # 选文件夹上传时浏览器会带 webkitRelativePath，用它还原目录结构；顺序与 files 对齐
    paths = request.form.getlist('paths')
    uploads = []
    for i, f in enumerate(files):
        rel = (paths[i] if i < len(paths) and paths[i].strip() else '') or f.filename or f'file{i}'
        rel = rel.replace('\\', '/')
        uploads.append((rel, rel.rsplit('/', 1)[-1], f.read()))

    try:
        images, rosters, zips = bt.unpack(uploads)
    except bt.BatchError as e:
        return _err(str(e))
    if not images:
        return _err('没找到图片（支持 png/jpg/bmp/webp/tif；'
                    'zip 请确认压缩包里是图片而不是又一层无关文件）')

    exam = _load_roster(exam, request.files.get('roster'), rosters)
    overrides = _merge_overrides(exam, _incoming_overrides())

    students = bt.group(images)
    for stu in students:
        pages, pageIssues = [], []
        for p in stu['pages']:
            try:
                _page_guard(tpl, p['page'])
            except ApiError as e:
                pageIssues.append(str(e))
                pages.append({'ok': False, 'name': p['name'], 'page': p['page'],
                              'hinted': p.get('hinted'),
                              'source': p['relpath'], 'error': str(e)})
                continue
            r, answers = _recognize_bytes(p['data'], p['name'], tpl,
                                          page_idx=p['page'], px_per_mm=px_per_mm,
                                          fill_min=fill_min, gap=gap, cnn_model=cnn_model)
            r['page'] = p['page']
            r['hinted'] = p.get('hinted')
            r['source'] = p['relpath']
            if not r['ok']:
                pageIssues.append(f'第 {p["page"] + 1} 面识别失败：{r["error"]}')
            pages.append(r)
        merged, conflicts = bt.merge_answers([r for r in pages if r['ok']])
        if conflicts:
            pageIssues.append('多页同一题号答案不一致：'
                              + '、'.join(f'第{c}题' for c in conflicts[:10]))
        # 页数据已经被识别结果取代 —— 原始字节就此丢掉，别把整个班留在内存里
        stu['pages'] = pages
        stu['answers'] = merged
        stu['conflicts'] = conflicts
        stu['pageIssues'] = pageIssues
        stu['source'] = '、'.join(p['source'] for p in pages if p.get('source'))

    # 识别完才知道卷面上涂的考号 → 用它校正/合并分组（文件名里没有考号也能对上人）
    students = bt.regroup(students, exam['roster'])
    students, warnings = bt.match(students, exam['roster'], overrides)

    if len(tpl['pages']) > 1:
        nohint = [p for stu in students for p in stu['pages'] if p.get('ok') and not p.get('hinted')]
        if nohint:
            warnings.insert(0, f'有 {len(nohint)} 张图找不到页序提示，已按上传顺序分页 —— '
                               f'这套模板有 {len(tpl["pages"])} 面，'
                               f'请在文件名里写明（如 正面/反面 或 _1/_2）后再传一次')

    # 批量是「一个班一次」的操作：整批替换（含之前试扫的散图），避免两批混算。
    # keep_manual：把已有人工复核 / 人工修正按考号搬回来 —— 重传扫描件不该毁掉人工劳动。
    STORE.save_students(exam['id'], students, keep_manual=True)
    STORE.clear_scans(exam['id'])
    STORE.set_overrides(exam['id'], overrides)
    STORE.set_active(exam['id'], 'batch',
                     ['stu-' + str(s['sid']) for s in students])

    return jsonify({'students': students, 'warnings': warnings,
                    'roster': _roster_info(STORE.exam(exam['id'])),
                    'exam': _exam_view(STORE.exam(exam['id'])),
                    'engine': _batch_engine(students),
                    'stats': {'images': len(images), 'students': len(students), 'zips': zips}})


@app.post('/api/roster')
@AUTH.require(*auth_mod.CAN_WRITE)
def upload_roster():
    """单独导名单：先导名单再传扫描件，或传完再补名单都行。"""
    exam = _exam()
    f = request.files.get('file')
    if not f:
        return _err('没有上传名单文件')
    try:
        roster, cols = bt.parse_roster(bt._read_text(f.read()))
    except bt.BatchError as e:
        return _err(str(e))
    STORE.set_roster(exam['id'], roster, cols, f.filename)
    exam = STORE.exam(exam['id'])
    students, warnings = _match(exam, exam['overrides'], save=True)
    return jsonify({'roster': _roster_info(exam), 'students': students,
                    'warnings': warnings})


@app.post('/api/batch/rematch')
@AUTH.require(*auth_mod.CAN_WRITE)
def rematch():
    """老师手工补录姓名 / 班级后重新套名单。补录会存进库里，刷新页面也在。"""
    exam = _exam()
    overrides = _merge_overrides(exam, _incoming_overrides())
    students, warnings = _match(exam, overrides, save=True)
    return jsonify({'students': students, 'warnings': warnings,
                    'roster': _roster_info(exam)})


@app.get('/api/students')
def get_students():
    exam = _exam(create=False)
    students, warnings = _students_view(exam)
    return jsonify({'students': students, 'warnings': warnings,
                    'roster': _roster_info(exam), 'exam': _exam_view(exam)})


# ---------------------------------------------------------------- 路由：阅卷工作台
#
# 阅卷工作台是「在已识别结果上做人工复核」的一层，不是新的识别流程。
# 复核结论（逐题改判 / 复核分 / 待复核标记 / 备注）存在每个考生的 data.grading 里，
# 跟 answers 走同一条落库/读回路径 —— 刷新、重新套名单、重启都不丢。

def _sanitize_grading(body):
    """把前端传来的 grading 收成规整形状，坏字段直接丢掉而不是静默乱存。"""
    g = body.get('grading') if isinstance(body, dict) else None
    if not isinstance(g, dict):
        raise ApiError('grading 必须是对象')
    overrides = {}
    for k, v in (g.get('overrides') or {}).items():
        if str(k).lstrip('-').isdigit():
            overrides[int(k)] = bool(v)
    ms = g.get('manualScore')
    man = ms if isinstance(ms, (int, float)) and not isinstance(ms, bool) else None
    return {'overrides': overrides,
            'manualScore': man,
            'review': bool(g.get('review')),
            'note': str(g.get('note') or '')}


@app.post('/api/grade')
@AUTH.require(*auth_mod.CAN_WRITE)
def grade():
    exam = _exam()
    body = request.get_json(silent=True) or {}
    sid = str(body.get('sid') or '').strip()
    if not sid:
        return _err('没给考号')
    try:
        grading = _sanitize_grading(body)
    except ApiError as e:
        return _err(e)
    try:
        STORE.set_student_grading(exam['id'], sid, grading)
    except store_mod.StoreError as e:
        return _err(str(e), 404)
    return jsonify({'ok': True, 'sid': sid, 'grading': grading})


# ---------------------------------------------------------------- 路由：人工修正
#
# 与「复核（grading）」的区别：复核改的是**判分结论**，这里改的是**答案本身**。
# 机器把 B 读成 C，就该用这里改成 B —— 分布统计、导出、误判率都会跟着对。
# 两者的落库路径完全一样（都是考生/扫描记录里的一个键），所以刷新/重启都不丢。

@app.post('/api/fix')
@AUTH.require(*auth_mod.CAN_WRITE)
def set_fixes():
    """保存某个考生（或某张扫描件）的人工修正表。

    body: {'sid': '20260101', 'fixes': {'3': 'B', '7': {'answer': 'AC', 'note': '…'}}}
          {'rid': '<扫描 id>', 'fixes': {...}}
    fixes 为 {} 表示「清空这个人所有修正」（回到机器原读）。
    """
    exam = _exam()
    body = request.get_json(silent=True) or {}
    who = (g.user or {}).get('username') or ''
    try:
        fxs = fixes_mod.normalize_all(body.get('fixes'), who=who)
    except fixes_mod.FixError as e:
        return _err(str(e))

    sid = str(body.get('sid') or '').strip()
    rid = str(body.get('rid') or '').strip()
    if not sid and not rid:
        return _err('没给考号（sid）或扫描件 id（rid）')
    try:
        if rid:
            STORE.set_scan_fixes(exam['id'], rid, fxs)
        else:
            STORE.set_student_fixes(exam['id'], sid, fxs)
    except store_mod.StoreError as e:
        return _err(str(e), 404)

    # 回吐合并后的生效答案 —— 前端拿到就能直接刷新那一行，不用再拉整页。
    if rid:
        row = next((s for s in STORE.scans(exam['id'], [rid])), None)
        answers = fixes_mod.apply((row or {}).get('answers') or {}, fxs)[0] if row else {}
    else:
        stu = STORE.students(exam['id'], [sid])
        answers = fixes_mod.apply((stu[0].get('answers') if stu else {}) or {}, fxs)[0]
    return jsonify({'ok': True, 'sid': sid or None, 'rid': rid or None,
                    'fixes': {str(k): v for k, v in fxs.items()},
                    'answers': {str(k): v for k, v in answers.items()}})


@app.post('/api/fix/sid')
@AUTH.require(*auth_mod.CAN_WRITE)
def fix_sid():
    """改正卷面考号。机器读错考号 = 整份卷子归错人，必须能改。"""
    exam = _exam()
    body = request.get_json(silent=True) or {}
    sid = str(body.get('sid') or '').strip()
    new_sid = str(body.get('newSid') or '').strip()
    rid = str(body.get('rid') or '').strip()
    if not new_sid:
        return _err('没给新考号')
    if len(new_sid) > 40:
        return _err('考号过长（上限 40 字符）')
    try:
        if rid:
            STORE.set_scan_sid(exam['id'], rid, new_sid)
        else:
            # 批量那条路：考号是主键的一部分，改名等于搬一行
            STORE.set_student_sid(exam['id'], sid, new_sid)
    except store_mod.StoreError as e:
        return _err(str(e), 404)
    return jsonify({'ok': True, 'sid': new_sid, 'oldSid': sid or None, 'rid': rid or None})


@app.get('/api/engine-accuracy')
def engine_accuracy():
    """按识别方案统计「老师改掉的比例」—— 用来判断哪套方案误判更少。

    只看出现过的题号（_qnos），并且用**机器原读**的 answers 做分母，
    免得被人工修正后的答案污染统计。
    """
    exam = _exam(create=False)
    if not exam:
        return jsonify({'rows': [], 'corrected': 0, 'decided': 0, 'rate': None,
                        'confusions': [], 'caveat': ''})
    sheets = _sheets(exam, applied=False)
    return jsonify(fixes_mod.engine_accuracy(sheets, qnos=set(_qnos(exam, sheets))))


@app.get('/api/gradebook')
def gradebook():
    """阅卷工作台的数据：每个考生的自动分、复核后分、逐题对错、复核标记。"""
    exam = _exam(create=False)
    if not exam:
        return jsonify({'students': [], 'exam': None, 'qnos': [], 'key': {}, 'hasKey': False,
                        'summary': {'count': 0, 'graded': 0, 'review': 0, 'avg': 0}})
    key = exam['answerKey']
    rules = exam.get('rules') or {}
    students, _ = _students_view(exam)
    qnos = _qnos(exam, [])
    rows = []
    for s in students:
        ans = s.get('answers') or {}
        grading = s.get('grading') or {}
        per_q, total, auto, final = scor.apply_rules(ans, qnos, key, rules, grading)
        rows.append({
            'sid': str(s.get('sid')), 'name': s.get('name') or '', 'cls': s.get('cls') or '',
            'matched': s.get('matched'), 'sidSource': s.get('sidSource'),
            'auto': auto, 'total': total,
            'grading': grading,
            'correct': {str(k): v.get('auto') for k, v in per_q.items()},
            'per_q': {str(k): v for k, v in per_q.items()},
            'effective': final,
            # 逐题「生效答案 + 机器原读 + 方案来源」，前端逐题核对/改答案全靠它：
            #   answer / flag / by        —— 生效值（有修正就是修正后的）
            #   machine / machineFlag / machineBy / fixNote —— 机器当时读到什么
            'answers': {str(k): _ans_view(v) for k, v in ans.items()},
            'fixedQnos': s.get('fixedQnos') or [],
        })
    graded = sum(1 for r in rows if r['grading'])
    review = sum(1 for r in rows if r['grading'].get('review'))
    avg = (sum(r['effective'] for r in rows) / len(rows)) if rows else 0
    return jsonify({'exam': _exam_view(exam), 'qnos': qnos, 'key': key, 'hasKey': bool(key),
                    'rules': rules,
                    'students': rows,
                    'summary': {'count': len(rows), 'graded': graded,
                                'review': review, 'avg': round(avg, 1)}})


# ---------------------------------------------------------------- 路由：导出

@app.get('/api/roster.csv')
def roster_csv():
    """对账表：考号、考号从哪儿来的、几个人没交、有哪些问题要人工看。"""
    exam = _exam(create=False)
    students, _ = _students_view(exam)
    rows = [[s['sid'], s.get('name', ''), s.get('cls', ''),
             bt.SID_SOURCE_ZH.get(s.get('sidSource'), ''),
             len(s.get('pages') or []),
             s.get('note') or '',
             '；'.join(s.get('issues') or [])] for s in students]
    csv_text = st.to_csv(rows, ['考号', '姓名', '班级', '考号来源', '页数', '说明', '备注'])
    return Response(csv_text, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="roster.csv"'})


@app.post('/api/stats')
def stats_api():
    exam = _exam(create=False)
    body = request.get_json(silent=True) or {}
    key_text = body.get('key') or request.form.get('key') or ''
    ids = body.get('ids')
    if not ids and request.form.get('ids'):
        ids = request.form['ids'].split(',')
    # 没传标准答案就用考试上存着的那份 —— 老师不用每次都重输。
    # 判「有没有传」要看文本空不空，不能用 `or`：传了空串是想清空，`or` 会把它当没传。
    key = st.parse_key(key_text) if (key_text or '').strip() else exam['answerKey']
    sheets = _sheets(exam, ids)
    return jsonify(st.summarize(sheets, _qnos(exam, sheets), key or None))


@app.post('/api/export.csv')
def export_csv():
    exam = _exam(create=False)
    key_text = request.form.get('key', '')
    key = st.parse_key(key_text) if key_text.strip() else exam['answerKey']
    rules = exam.get('rules') or {}
    graded = request.form.get('graded') == '1'
    ids = request.form.get('ids', '').split(',') if request.form.get('ids') else None
    sheets = _sheets(exam, ids)
    if any(s.get('sid') for s in sheets):
        sheets.sort(key=lambda s: bt.natkey(str(s.get('sid') or '')))
    qnos = _qnos(exam, sheets)
    with_id = any(s.get('sid') for s in sheets)

    # 复核分导出：把人工改判合并进去。grading 是按考号挂在考生上的，先建一张映射。
    gmap = {}
    if graded and key:
        for s in _students_view(exam)[0]:
            gmap[str(s.get('sid'))] = s.get('grading')

    head = (['考号', '姓名', '班级'] if with_id else []) + ['文件'] \
        + [str(q) for q in qnos] + (['复核分' if graded else '得分'] if key else [])
    rows = []
    for s in sheets:
        row = [s.get('sid', ''), s.get('stu', ''), s.get('cls', '')] if with_id else []
        row += [s.get('name', '')] + [s['answers'].get(q, {}).get('answer') or '' for q in qnos]
        if key:
            _, total, auto, final = scor.apply_rules(
                s['answers'], qnos, key, rules, gmap.get(str(s.get('sid'))) if graded else None)
            v = final if graded else auto
            # 整数分显示成整数（'4' 不是 '4.0'），规则可能出小数（半对=0.5）时保留小数。
            row.append(int(v) if float(v).is_integer() else round(v, 2))
        rows.append(row)
    csv_text = st.to_csv(rows, head)
    return Response(csv_text, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="omr-answers.csv"'})


@app.get('/api/rules')
def get_rules():
    """读当前考试的评分规则 + 每题标准答案（供规则编辑器初始化）。"""
    exam = _exam(create=False)
    if not exam:
        return jsonify({'error': '还没有考试'})
    return jsonify({
        'exam': _exam_view(exam),
        'rules': exam.get('rules') or {},
        'key': exam['answerKey'],
        'qnos': _qnos(exam, []),
    })


@app.post('/api/rules')
def set_rules():
    """保存评分规则：{题号: rule}。只存合法字段，非法丢弃。"""
    exam = _exam(create=False)
    if not exam:
        return jsonify({'error': '还没有考试'})
    body = request.get_json(silent=True) or {}
    raw = body.get('rules')
    if not isinstance(raw, dict):
        return jsonify({'error': 'rules 必须是 {题号: 规则} 的字典'})
    rules = {}
    for k, v in raw.items():
        r = scor.normalize_rule(v)
        if r:
            try:
                rules[str(int(k))] = r
            except (TypeError, ValueError):
                rules[str(k)] = r
    STORE.set_rules(exam['id'], rules)
    return jsonify({'ok': True, 'rules': rules,
                    'summary': '已保存 %d 条评分规则' % len(rules)})


@app.get('/api/overlay/<rid>.png')
def overlay(rid):
    # 校对图按 id 取，不按考试分目录 —— 文件名是随机的 12 位 hex，猜到别人的等于猜 16^12 次
    return send_from_directory(DATA, rid + '.png', mimetype='image/png')


# ---------------------------------------------------------------- 路由：账号

@app.post('/api/password')
def change_password():
    """本人改口令。改完自己所有会话失效（包括当前这个），所以要重新登录。"""
    body = request.get_json(silent=True) or {}
    try:
        AUTH.change_password(g.user, body.get('old'), body.get('new'))
    except auth_mod.AuthError as e:
        return _err(e, e.code)
    return auth_mod.clear_cookie(jsonify({'ok': True, 'relogin': True}))


@app.get('/api/users')
@AUTH.require(*auth_mod.CAN_ADMIN)
def list_users():
    return jsonify({'users': STORE.list_users()})


@app.post('/api/users')
@AUTH.require(*auth_mod.CAN_ADMIN)
def create_user():
    body = request.get_json(silent=True) or {}
    try:
        u = STORE.create_user(body.get('username'), auth_mod.hash_password(body.get('password')),
                              role=body.get('role') or 'teacher',
                              display=body.get('display') or '')
    except (store_mod.StoreError, ValueError) as e:
        return _err(e)
    return jsonify({'ok': True, 'user': {k: v for k, v in u.items() if k != 'pwd'}})


@app.post('/api/users/role')
@AUTH.require(*auth_mod.CAN_ADMIN)
def set_role():
    body = request.get_json(silent=True) or {}
    try:
        STORE.set_role(int(body.get('id')), body.get('role'))
    except (store_mod.StoreError, TypeError, ValueError) as e:
        return _err(e)
    return jsonify({'ok': True, 'users': STORE.list_users()})


@app.post('/api/users/password')
@AUTH.require(*auth_mod.CAN_ADMIN)
def set_user_password():
    """管理员帮人重置口令。顺手把那个人的会话全掐掉 —— 重置口令的常见原因就是账号被盗。"""
    body = request.get_json(silent=True) or {}
    try:
        uid = int(body.get('id'))
        STORE.set_password(uid, auth_mod.hash_password(body.get('password')))
        STORE.delete_user_sessions(uid)
    except (store_mod.StoreError, ValueError) as e:
        return _err(e)
    return jsonify({'ok': True})


@app.post('/api/users/delete')
@AUTH.require(*auth_mod.CAN_ADMIN)
def delete_user():
    body = request.get_json(silent=True) or {}
    try:
        uid = int(body.get('id'))
        if uid == g.user['id']:
            return _err('不能删掉自己')
        STORE.delete_user(uid)
    except (store_mod.StoreError, TypeError, ValueError) as e:
        return _err(e)
    return jsonify({'ok': True, 'users': STORE.list_users()})


# ---------------------------------------------------------------- 错误处理

@app.errorhandler(ApiError)
def _on_api_error(e):
    return _err(e, e.code)


@app.errorhandler(404)
def _on_404(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': '没有这个接口'}), 404
    return redirect('/')


def create_app():
    return app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8081))
    app.run(host='0.0.0.0', port=port, debug=False)
