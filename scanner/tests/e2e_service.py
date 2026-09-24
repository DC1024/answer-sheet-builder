# 服务级集成测试：对着「已经跑起来的」扫描服务走一遍完整业务流。
#
#   docker compose up -d                  # 或 python -m app.server
#   pip install requests
#   python tests/e2e_service.py                       # 默认 http://127.0.0.1:8081
#   BASE=http://192.168.1.10:8081 python tests/e2e_service.py
#
# 覆盖：上传模板 → 上传扫描图（干净 + 手机拍照合成）→ 比对答案 → 拉校对图
#       → 班级统计 → 导出 CSV，以及判分口径的一致性。
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tests import _fixtures      # noqa: E402

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081').rstrip('/')
FIX = _fixtures.FIX
FAILS = []


def check(ok_, label, extra=''):
    print(('  ✅ ' if ok_ else '  ❌ ') + label + (f'  {extra}' if extra else ''))
    if not ok_:
        FAILS.append(label)


# ---- 极简 multipart 客户端（不引入第三方依赖） ---------------------------------
def _mp(fields, files):
    """fields: {name: str}；files: [(name, filename, bytes, ctype)]"""
    boundary = '----asbE2E' + os.urandom(8).hex()
    out = []
    for k, v in fields.items():
        out += [f'--{boundary}', f'Content-Disposition: form-data; name="{k}"', '', str(v)]
    for name, fn, data, ctype in files:
        out += [f'--{boundary}',
                f'Content-Disposition: form-data; name="{name}"; filename="{fn}"',
                f'Content-Type: {ctype}', '', data]
    out += [f'--{boundary}--', '']
    body = bytearray()
    for part in out:
        body += part.encode('utf-8') if isinstance(part, str) else part
        body += b'\r\n'
    return bytes(body), f'multipart/form-data; boundary={boundary}'


def req(method, path, fields=None, files=None, json_body=None, raw=False):
    url = BASE + path
    headers = {}
    if json_body is not None:
        data = json.dumps(json_body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    elif files or fields:
        data, ct = _mp(fields or {}, files or [])
        headers['Content-Type'] = ct
    else:
        data = None
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            body = resp.read()
            return resp.status, (body if raw else json.loads(body or b'null'))
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body or b'null')
        except Exception:
            return e.code, body


def main():
    expected = json.load(open(os.path.join(FIX, 'expected.json'), encoding='utf-8'))
    clean = sorted(f for f in os.listdir(FIX) if f.startswith('s') and f.endswith('.png'))

    print(f'=== 0. 连通性 {BASE} ===')
    try:
        st, _ = req('GET', '/api/template')
        check(st == 200, 'GET /api/template 返回 200', f'HTTP {st}')
        st, _ = req('GET', '/', raw=True)
        check(st == 200, 'GET / 页面可达', f'HTTP {st}')
    except Exception as e:
        print('  ❌ 连不上：', e)
        return 1

    print('\n=== 1. 上传阅卷模板 ===')
    tpl_bytes = open(os.path.join(FIX, 'template.json'), 'rb').read()
    st, j = req('POST', '/api/template', files=[('file', 'template.json', tpl_bytes, 'application/json')])
    check(st == 200 and j.get('ok'), '模板上传成功', str(j)[:150])
    s = j.get('summary') or {}
    check(s.get('questionCount') == 20, '模板题数 = 20', f"实测 {s.get('questionCount')}")

    def run_batch(tag, items, fill_min=None):
        """items: [(filename, bytes)]"""
        print(f'\n=== {tag} ===')
        files = [('files', fn, data, 'image/jpeg' if fn.endswith('.jpg') else 'image/png')
                 for fn, data in items]
        fields = {'pxPerMm': '8.0'}
        if fill_min:
            fields['fillMin'] = str(fill_min)
        st, j = req('POST', '/api/scan', fields=fields, files=files)
        res = j.get('results') or []
        check(len(res) == len(items), f'返回 {len(items)} 份结果', f'实测 {len(res)}')

        total = correct = 0
        flags = {}
        ids = []
        for it in res:
            if not it.get('ok'):
                check(False, f"{it.get('name')} 识别失败", str(it.get('error'))[:120])
                continue
            ids.append(it['id'])
            stem = os.path.splitext(it['name'])[0].replace('_phone', '')
            exp = expected.get(stem) or {}
            got = {q['no']: q['answer'] for q in it['questions']}
            for no, want in exp.items():
                if want is None:
                    continue
                total += 1
                if got.get(int(no)) == want:
                    correct += 1
            for q in it['questions']:
                flags[q['flag']] = flags.get(q['flag'], 0) + 1
        acc = correct / total * 100 if total else 0
        check(acc >= 95, f'平均正确率 {acc:.1f}% (≥95%)', f'{correct}/{total}')
        print('     状态分布:', flags)

        first = res[0]
        q3 = next((q for q in first['questions'] if q['no'] == 3), None)
        q8 = next((q for q in first['questions'] if q['no'] == 8), None)
        check(bool(q3) and q3['flag'] == 'blank', '第 3 题（未涂）→ blank', q3 and q3['flag'])
        check(bool(q8) and q8['flag'] == 'faint', '第 8 题（浅涂）→ faint', q8 and q8['flag'])

        st, png = req('GET', f"/api/overlay/{ids[0]}.png", raw=True)
        check(st == 200 and png[:8] == b'\x89PNG\r\n\x1a\n',
              '校对图可取且是合法 PNG', f'HTTP {st}, {len(png)} bytes')
        return ids

    ids_scan = run_batch('A. 干净扫描（300dpi 级）',
                         [(n, open(os.path.join(FIX, n), 'rb').read()) for n in clean])
    phone = _fixtures.phone_variants(clean)
    ids_photo = run_batch('B. 手机拍照合成',
                          [(n, open(p, 'rb').read()) for n, p in phone])

    print('\n=== C. 班级统计 ===')
    # 用 s01 当标准答案：s01/s05 的作答相同 → 两者都该满分
    key = ' '.join(f'{int(no)}{a}' for no, a in
                   sorted(expected['s01'].items(), key=lambda kv: int(kv[0])) if a)
    print('     标准答案:', key)
    st, sm = req('POST', '/api/stats', json_body={'key': key, 'ids': ids_scan})
    check(st == 200, '统计接口 200', f'HTTP {st}')
    check(len(sm.get('questions') or []) == 20, '每题统计 20 条', f"实测 {len(sm.get('questions') or [])}")
    sheets = sm.get('sheets') or []
    check(bool(sheets), '返回每份卷子的判分')
    if sheets:
        by = {x['name']: x for x in sheets}
        # 标准答案里没有第 3 题（故意留空）→ 满分是 19 而不是 20
        check(by['s01.png']['score'] == by['s01.png']['total'] == 19,
              's01 满分 19/19（第 3 题无标准答案）', by['s01.png'])
        check(by['s05.png']['score'] == 19, 's05（与 s01 作答相同）也满分', by['s05.png'])
        others = [x for x in sheets if x['name'] not in ('s01.png', 's05.png')]
        check(all(x['score'] < 19 for x in others),
              '其余卷子用 s01 答案判分低于满分（确实在比对，不是白送分）',
              [f"{x['name']}:{x['score']}/{x['total']}" for x in sheets])

    print('\n=== D. 导出 CSV ===')
    st, csv_text = req('POST', '/api/export.csv',
                       fields={'key': key, 'ids': ','.join(ids_scan)}, raw=True)
    check(st == 200, 'CSV 接口 200', f'HTTP {st}')
    lines = [l for l in csv_text.decode('utf-8-sig').strip().splitlines() if l.strip()]
    check(len(lines) == 7, 'CSV 行数 = 7（表头 + 6 份）', f'实测 {len(lines)}')
    print('     表头:', lines[0][:110] if lines else '(空)')
    print('     首行:', lines[1][:110] if len(lines) > 1 else '(空)')
    s01_row = next((l for l in lines if l.startswith('s01')), '')
    check(s01_row.endswith(',19'), 'CSV 里 s01 得分 = 19（与统计接口口径一致）', s01_row[-14:])

    print('\n' + '=' * 56)
    if FAILS:
        print(f'⚠️  {len(FAILS)} 项未通过：')
        for f in FAILS:
            print('   -', f)
        return 1
    print('🎉 服务级端到端全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
