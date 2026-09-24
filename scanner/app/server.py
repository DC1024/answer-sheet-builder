# 答题卡扫描识别服务：上传阅卷模板 + 扫描图 → 识别选择题填涂 → 汇总统计
# 纯 OpenCV，无模型下载，可完全离线运行。
#
# 两条识别入口共用同一条识别路径（_recognize_bytes）：
#   POST /api/scan    单张 / 少量图片，来一批识别一批，结果累积
#   POST /api/batch   一个班的扫描件（zip 或整个文件夹）+ 名单，按考号归组、多页合并、跟名单匹配
import json
import os
import uuid
import numpy as np
import cv2
from flask import Flask, jsonify, request, send_from_directory, Response

from . import omr
from . import batch as bt
from . import stats as st

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
os.makedirs(DATA, exist_ok=True)

app = Flask(__name__, static_folder=STATIC, static_url_path='')
# 一个班 50 人 × 2 面 × 1MB 很容易过 100MB —— 给足余量（反正在内网跑）
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024

# results: id -> {'name','answers','sid','stu','cls','source'}
# active:  最近一次识别产出的结果 id。统计/导出默认只针对这一批，
#          否则「先扫 3 张试试、再扫一个班」会把两批混在一起算。
STATE = {'template': None, 'results': {}, 'active': [],
         'roster': {}, 'rosterCols': {}, 'rosterSource': None,
         'students': [], 'warnings': []}


# ---------------------------------------------------------------- 识别

def _decode(data):
    buf = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise omr.OmrError('无法解码图片（仅支持 PNG / JPG 等常见格式）')
    return img


def _recognize_bytes(data, name, tpl, page_idx=0, px_per_mm=8.0, fill_min=0.5, gap=0.15):
    """识别一张图 → (结果字典, answers)。识别失败时 answers 为 None。

    单张扫描和批量上传都走这里 —— 免得两条路各修一次、还修得不一样。
    """
    try:
        img = _decode(data)
        r = omr.recognize(img, tpl, page_idx=page_idx, px_per_mm=px_per_mm,
                          fill_min=fill_min, gap=gap)
        rid = uuid.uuid4().hex[:12]
        png = r.pop('overlayPng', None)
        saved = _save_overlay(rid, png) if png else False
        answers = {q['no']: {'answer': q['answer'], 'flag': q['flag'], 'best': q['best'],
                             'second': q['second'], 'ratios': q['ratios'], 'inks': q['inks']}
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


def _require_template():
    tpl = STATE['template']
    if not tpl:
        raise bt.BatchError('请先上传「阅卷模板」')
    return tpl


def _page_guard(tpl, page_idx):
    """越界的页序号必须报错，不能放过去。

    omr._template_quad() 会把越界页序号夹到最后一页 —— 对「多传了一页」的卷子，
    结果是拿错的模板面去采样，答案看着正常但是错的。这是阅卷工具里最坏的失败方式，
    所以在入口就把话说明白。
    """
    n = len(tpl['pages'])
    if page_idx >= n:
        raise bt.BatchError(f'页序号 {page_idx} 超出模板范围（模板共 {n} 面）——'
                            f'请检查文件名里的页序提示，或重新导出正确的模板')


# ---------------------------------------------------------------- 结果集

def _label(stu):
    """「2026010234 张伟明」—— 解析不出考号时退回文件名。"""
    parts = [str(stu.get('sid') or ''), stu.get('name') or '']
    txt = ' '.join(p for p in parts if p).strip()
    return txt or (stu.get('source') or '未命名')


def _sheets(ids=None):
    """取结果集。默认只取「最近一次识别」那一批。"""
    if ids is None:
        ids = STATE['active'] or list(STATE['results'])
    return [dict(STATE['results'][i], id=i) for i in ids if i in STATE['results']]


def _qnos(sheets):
    """题号全集：模板是权威（含学生都没填的题），没有模板才退回结果里出现过的题号。"""
    if STATE['template']:
        return sorted({q['no'] for p in STATE['template']['pages'] for q in p.get('questions', [])})
    return sorted({q for s in sheets for q in s['answers']})


# ---------------------------------------------------------------- 名单

def _overrides():
    """人工补录数据（考号 → 姓名/班级）。

    两种传法都要认：批量上传时跟文件一起当表单字段带过来，重新套用名单时用 JSON 体。
    """
    raw = request.form.get('overrides')
    if not raw:
        body = request.get_json(silent=True)
        d = body.get('overrides') if isinstance(body, dict) else None
        return d if isinstance(d, dict) else {}
    try:
        d = json.loads(raw)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _load_roster(explicit, embedded):
    """名单来源：显式上传的 > zip 里自带的；都没有就沿用上一份（同一个班的多次上传）。

    返回 (roster, error)。只有拿到新名单时才覆盖 —— 这样「先单独导名单、再传扫描件」
    的用法不会因为第二次没带名单文件而丢掉名单。
    """
    if explicit is not None and explicit.filename:
        try:
            roster, cols = bt.parse_roster(bt._read_text(explicit.read()))
        except bt.BatchError as e:
            return None, '名单解析失败：' + str(e)
        STATE.update(roster=roster, rosterCols=cols, rosterSource=explicit.filename)
    else:
        found = bt.find_roster(embedded)
        if found:
            roster, cols, src = found
            STATE.update(roster=roster, rosterCols=cols, rosterSource=src)
    return STATE['roster'], None


def _roster_info():
    return {'count': len(STATE['roster']), 'columns': STATE['rosterCols'],
            'source': STATE['rosterSource']}


def _rematch():
    """重新套一次名单 —— 只改姓名/班级这类展示字段，不碰已经识别出来的答案。"""
    students, warnings = bt.match(STATE['students'], STATE['roster'], _overrides())
    STATE['students'], STATE['warnings'] = students, warnings
    for stu in students:
        rec = STATE['results'].get('stu-' + str(stu['sid']))
        if rec:
            rec.update({'name': _label(stu), 'stu': stu['name'], 'cls': stu['cls']})
    return students


# ---------------------------------------------------------------- 路由

@app.get('/')
def index():
    return send_from_directory(STATIC, 'index.html')


@app.post('/api/template')
def upload_template():
    f = request.files.get('file')
    if not f:
        return jsonify({'error': '没有上传文件'}), 400
    try:
        tpl = omr.load_template(f.read().decode('utf-8'))
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    STATE['template'] = tpl
    STATE['results'] = {}
    STATE['active'] = []
    STATE['students'] = []
    STATE['warnings'] = []
    return jsonify({'ok': True, 'summary': omr.template_summary(tpl)})


@app.get('/api/template')
def get_template():
    tpl = STATE['template']
    if not tpl:
        return jsonify({'template': None})
    return jsonify({'template': omr.template_summary(tpl)})


@app.post('/api/scan')
def scan():
    try:
        tpl = _require_template()
    except bt.BatchError as e:
        return jsonify({'error': str(e)}), 400
    files = request.files.getlist('files') or ([request.files['file']] if 'file' in request.files else [])
    if not files:
        return jsonify({'error': '没有上传扫描图'}), 400
    page_idx, px_per_mm, fill_min, gap = _params()
    try:
        _page_guard(tpl, page_idx)
    except bt.BatchError as e:
        return jsonify({'error': str(e)}), 400

    out, ids = [], []
    for f in files:
        r, answers = _recognize_bytes(f.read(), f.filename, tpl,
                                      page_idx, px_per_mm, fill_min, gap)
        if answers is not None:
            STATE['results'][r['id']] = {'name': f.filename, 'answers': answers,
                                         'source': f.filename}
            ids.append(r['id'])
        out.append(r)
    if ids:
        STATE['active'] = ids          # 统计/导出针对刚识别的这一批
    return jsonify({'results': out})


@app.post('/api/batch')
def batch_api():
    """一次一个班：zip / 整个文件夹 / 一堆散图 + 可选名单。"""
    try:
        tpl = _require_template()
    except bt.BatchError as e:
        return jsonify({'error': str(e)}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': '没有上传扫描件（zip 压缩包 / 整张图片 / 整个文件夹都行）'}), 400
    page_idx, px_per_mm, fill_min, gap = _params()

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
        return jsonify({'error': str(e)}), 400
    if not images:
        return jsonify({'error': '没找到图片（支持 png/jpg/bmp/webp/tif；'
                                 'zip 请确认压缩包里是图片而不是又一层无关文件）'}), 400

    roster, err = _load_roster(request.files.get('roster'), rosters)
    if err:
        return jsonify({'error': err}), 400

    students = bt.group(images)
    for stu in students:
        pages, pageIssues = [], []
        for p in stu['pages']:
            try:
                _page_guard(tpl, p['page'])
            except bt.BatchError as e:
                pageIssues.append(str(e))
                pages.append({'ok': False, 'name': p['name'], 'page': p['page'],
                              'hinted': p.get('hinted'),
                              'source': p['relpath'], 'error': str(e)})
                continue
            r, answers = _recognize_bytes(p['data'], p['name'], tpl,
                                          page_idx=p['page'], px_per_mm=px_per_mm,
                                          fill_min=fill_min, gap=gap)
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
    students = bt.regroup(students, roster)
    students, warnings = bt.match(students, roster, _overrides())

    if len(tpl['pages']) > 1:
        nohint = [p for stu in students for p in stu['pages'] if p.get('ok') and not p.get('hinted')]
        if nohint:
            warnings.insert(0, f'有 {len(nohint)} 张图找不到页序提示，已按上传顺序分页 —— '
                               f'这套模板有 {len(tpl["pages"])} 面，'
                               f'请在文件名里写明（如 正面/反面 或 _1/_2）后再传一次')
    STATE['students'], STATE['warnings'] = students, warnings

    # 批量是「一个班一次」的操作：整批替换，避免上一批的学生残留
    STATE['results'] = {}
    for stu in students:
        STATE['results']['stu-' + str(stu['sid'])] = {
            'name': _label(stu), 'answers': stu['answers'],
            'sid': str(stu['sid']), 'stu': stu['name'], 'cls': stu['cls'],
            'source': stu['source'],
        }
    STATE['active'] = list(STATE['results'])

    return jsonify({'students': students, 'warnings': warnings, 'roster': _roster_info(),
                    'stats': {'images': len(images), 'students': len(students), 'zips': zips}})


@app.post('/api/roster')
def upload_roster():
    """单独导名单：先导名单再传扫描件，或传完再补名单都行。"""
    f = request.files.get('file')
    if not f:
        return jsonify({'error': '没有上传名单文件'}), 400
    try:
        roster, cols = bt.parse_roster(bt._read_text(f.read()))
    except bt.BatchError as e:
        return jsonify({'error': str(e)}), 400
    STATE.update(roster=roster, rosterCols=cols, rosterSource=f.filename)
    students = _rematch()
    return jsonify({'roster': _roster_info(), 'students': students,
                    'warnings': STATE['warnings']})


@app.post('/api/batch/rematch')
def rematch():
    """老师手工补录姓名 / 班级后重新套名单。"""
    students = _rematch()
    return jsonify({'students': students, 'warnings': STATE['warnings'],
                    'roster': _roster_info()})


@app.get('/api/students')
def get_students():
    return jsonify({'students': STATE['students'], 'warnings': STATE['warnings'],
                    'roster': _roster_info()})


@app.get('/api/roster.csv')
def roster_csv():
    """对账表：考号、考号从哪儿来的、几个人没交、有哪些问题要人工看。"""
    rows = [[s['sid'], s.get('name', ''), s.get('cls', ''),
             bt.SID_SOURCE_ZH.get(s.get('sidSource'), ''),
             len(s.get('pages') or []),
             s.get('note') or '',
             '；'.join(s.get('issues') or [])] for s in STATE['students']]
    csv_text = st.to_csv(rows, ['考号', '姓名', '班级', '考号来源', '页数', '说明', '备注'])
    return Response(csv_text, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="roster.csv"'})


@app.get('/api/overlay/<rid>.png')
def overlay(rid):
    return send_from_directory(DATA, rid + '.png', mimetype='image/png')


@app.post('/api/stats')
def stats_api():
    body = request.get_json(silent=True) or {}
    key_text = body.get('key') or request.form.get('key') or ''
    ids = body.get('ids')
    if not ids and request.form.get('ids'):
        ids = request.form['ids'].split(',')
    key = st.parse_key(key_text)
    sheets = _sheets(ids)
    return jsonify(st.summarize(sheets, _qnos(sheets), key or None))


@app.post('/api/export.csv')
def export_csv():
    key = st.parse_key(request.form.get('key', ''))
    ids = request.form.get('ids', '').split(',') if request.form.get('ids') else None
    sheets = _sheets(ids)
    if any(s.get('sid') for s in sheets):
        sheets.sort(key=lambda s: bt.natkey(str(s.get('sid') or '')))
    qnos = _qnos(sheets)
    with_id = any(s.get('sid') for s in sheets)

    head = (['考号', '姓名', '班级'] if with_id else []) + ['文件'] \
        + [str(q) for q in qnos] + (['得分'] if key else [])
    rows = []
    for s in sheets:
        row = [s.get('sid', ''), s.get('stu', ''), s.get('cls', '')] if with_id else []
        row += [s.get('name', '')] + [s['answers'].get(q, {}).get('answer') or '' for q in qnos]
        if key:
            row.append(st.score(s['answers'], qnos, key))
        rows.append(row)
    csv_text = st.to_csv(rows, head)
    return Response(csv_text, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="omr-answers.csv"'})


def create_app():
    return app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8081))
    app.run(host='0.0.0.0', port=port, debug=False)
