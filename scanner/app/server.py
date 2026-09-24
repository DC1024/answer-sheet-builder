# 答题卡扫描识别服务：上传阅卷模板 + 扫描图 → 识别选择题填涂 → 汇总统计
# 纯 OpenCV，无模型下载，可完全离线运行。
import io
import os
import uuid
import numpy as np
import cv2
from flask import Flask, jsonify, request, send_from_directory, Response

from . import omr
from . import stats as st

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
os.makedirs(DATA, exist_ok=True)

app = Flask(__name__, static_folder=STATIC, static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024

STATE = {'template': None, 'results': {}}     # results: id -> {'name','answers','overlay'}


def _read_image(file):
    buf = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise omr.OmrError('无法解码图片（仅支持 PNG / JPG 等常见格式）')
    return img


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
    return jsonify({'ok': True, 'summary': omr.template_summary(tpl)})


@app.get('/api/template')
def get_template():
    tpl = STATE['template']
    if not tpl:
        return jsonify({'template': None})
    return jsonify({'template': omr.template_summary(tpl)})


@app.post('/api/scan')
def scan():
    tpl = STATE['template']
    if not tpl:
        return jsonify({'error': '请先上传「阅卷模板」'}), 400
    files = request.files.getlist('files') or ([request.files['file']] if 'file' in request.files else [])
    if not files:
        return jsonify({'error': '没有上传扫描图'}), 400
    page_idx = int(request.form.get('page', 0) or 0)
    px_per_mm = float(request.form.get('dpi', 0) or 0) or 8.0
    if request.form.get('pxPerMm'):
        px_per_mm = float(request.form['pxPerMm'])
    fill_min = float(request.form.get('fillMin', 0.5) or 0.5)
    gap = float(request.form.get('gap', 0.15) or 0.15)

    out = []
    for f in files:
        try:
            img = _read_image(f)
            r = omr.recognize(img, tpl, page_idx=page_idx, px_per_mm=px_per_mm,
                              fill_min=fill_min, gap=gap)
            rid = uuid.uuid4().hex[:12]
            png = r.pop('overlayPng', None)
            if png:
                with open(os.path.join(DATA, rid + '.png'), 'wb') as fh:
                    fh.write(png)
            answers = {q['no']: {'answer': q['answer'], 'flag': q['flag'],
                                 'best': q['best'], 'second': q['second'],
                                 'ratios': q['ratios'], 'inks': q['inks']}
                       for q in r['questions']}
            STATE['results'][rid] = {'name': f.filename, 'answers': answers}
            r.update({'id': rid, 'name': f.filename, 'ok': True})
        except Exception as e:
            r = {'ok': False, 'name': f.filename, 'error': str(e)}
        out.append(r)
    return jsonify({'results': out})


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
    sheets = [{'name': STATE['results'][i]['name'], 'answers': STATE['results'][i]['answers']}
              for i in (ids or list(STATE['results'])) if i in STATE['results']]
    qnos = sorted({q['no'] for p in STATE['template']['pages'] for q in p.get('questions', [])}) \
        if STATE['template'] else sorted(q for s in sheets for q in s['answers'])
    return jsonify(st.summarize(sheets, qnos, key or None))


@app.post('/api/export.csv')
def export_csv():
    key = st.parse_key(request.form.get('key', ''))
    ids = request.form.get('ids', '').split(',') if request.form.get('ids') else list(STATE['results'])
    sheets = [{'name': STATE['results'][i]['name'], 'answers': STATE['results'][i]['answers']}
              for i in ids if i in STATE['results']]
    qnos = sorted({q['no'] for p in STATE['template']['pages'] for q in p.get('questions', [])}) \
        if STATE['template'] else sorted(q for s in sheets for q in s['answers'])
    rows = []
    head = ['文件'] + [str(q) for q in qnos] + (['得分'] if key else [])
    for s in sheets:
        row = [s['name']] + [s['answers'].get(q, {}).get('answer') or '' for q in qnos]
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
