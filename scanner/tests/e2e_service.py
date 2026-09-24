# 服务级集成测试：对着「已经跑起来的」扫描服务走一遍完整业务流。
#
#   docker compose up -d                  # 或 python -m app.server
#   python tests/e2e_service.py                       # 默认 http://127.0.0.1:8081
#   BASE=http://192.168.1.10:8081 python tests/e2e_service.py
#
# 覆盖：上传模板 → 上传扫描图（干净 + 手机拍照合成）→ 比对答案 → 拉校对图
#       → 班级统计 → 导出 CSV，以及判分口径的一致性；
#       再有批量上传：zip + 内嵌名单 → 归组/匹配/多页 → 统计导出带考号姓名班级
#       → 人工补录后重新匹配 → 页序越界必须报错。
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile

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
    """fields: {name: str} 或 [(name, value)]（后者用于 paths 这种重复字段）；
    files: [(name, filename, bytes, ctype)]"""
    items = list(fields.items()) if isinstance(fields, dict) else list(fields)
    boundary = '----asbE2E' + os.urandom(8).hex()
    out = []
    for k, v in items:
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
            if it.get('overlay') is False:
                check(False, '校对图写入失败（检查 data/ 挂载目录是否存在且可写）',
                      str(it.get('overlayError'))[:120])
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

    # ------------------------------------------------------------ 批量上传
    def img(name):
        return open(os.path.join(FIX, name), 'rb').read()

    def make_zip(entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, data in entries:
                zf.writestr(name, data)
        return buf.getvalue()

    def post_zip(tag, zip_bytes, arcname='一个班.zip', extra=None, roster=None):
        print(f'\n=== {tag} ===')
        fields = {'pxPerMm': '8.0'}
        fields.update(extra or {})
        files = [('files', arcname, zip_bytes, 'application/zip')]
        if roster:
            files.append(('roster', '名单.csv', roster.encode('utf-8'), 'text/csv'))
        st, j = req('POST', '/api/batch', fields=fields, files=files)
        check(st == 200, '批量接口 200', f'HTTP {st} {str(j)[:160]}')
        return j

    ROSTER = ('考号,姓名,班级\n'
              '2026010234,张伟明,高三(12)班\n'
              '2026010235,李思,高三(12)班\n'
              '2026010236,王五,高三(12)班\n'
              '2026010299,赵六,高三(12)班\n')

    # 目录名给考号 / 文件名给考号 / 名单夹在 zip 里 / 顺带塞 macOS 垃圾
    zip_main = make_zip([
        ('一个班/2026010234/正面.png', img('s01.png')),
        ('一个班/2026010235/正面.png', img('s02.png')),
        ('一个班/__MACOSX/._2026010235', b'junk'),
        ('一个班/2026010235/._正面.png', b'junk'),
        ('一个班/.DS_Store', b'junk'),
        ('一个班/2026010236.png', img('s03.png')),
        ('一个班/2026010237.png', img('s04.png')),
        ('一个班/名单.csv', ROSTER.encode('utf-8')),
    ])
    j = post_zip('E. 批量上传（zip + 内嵌名单 + macOS 垃圾）', zip_main)
    stus = j.get('students') or []
    check(len(stus) == 4, '归组出 4 位考生', f'实测 {len(stus)}')
    check((j.get('stats') or {}).get('images') == 4, '图片数 = 4（垃圾文件已跳过）',
          str(j.get('stats')))
    check([s['sid'] for s in stus] == ['2026010234', '2026010235', '2026010236', '2026010237'],
          '考生按考号自然序排列', str([s['sid'] for s in stus]))
    check(j.get('roster', {}).get('count') == 4, 'zip 内嵌名单被识别（4 行）',
          str(j.get('roster')))

    # 名单匹配
    m = {s['sid']: s for s in stus}
    check(m['2026010234']['name'] == '张伟明' and m['2026010234']['cls'] == '高三(12)班'
          and m['2026010234']['matched'] is True, '清单里的人匹配到姓名+班级',
          str(m['2026010234'].get('name')))
    check(m['2026010237']['matched'] is False
          and any('不在名单里' in i for i in m['2026010237']['issues']),
          '名单外的考号 → matched=False 并进待确认队列', str(m['2026010237']['issues']))
    warns = ' | '.join(j.get('warnings') or [])
    check('未交卷' in warns or '没交卷' in warns or '没上传' in warns,
          '提示名单里没交卷的人', warns[:120])
    check('不在名单里' in warns, '提示有考号不在名单里', warns[:120])

    # 答案正确性：批量路径的答案必须和单张路径一模一样
    SID2FIX = {'2026010234': 's01', '2026010235': 's02',
               '2026010236': 's03', '2026010237': 's04'}
    tot = cor = 0
    for s in stus:
        exp = expected.get(SID2FIX.get(s['sid'], '')) or {}
        for no, want in exp.items():
            if want is None:
                continue
            tot += 1
            # 答案字典过了 JSON，键是字符串
            if (s.get('answers') or {}).get(str(no), {}).get('answer') == want:
                cor += 1
    acc = cor / tot * 100 if tot else 0
    check(acc >= 95, f'批量识别平均正确率 {acc:.1f}% (≥95%)', f'{cor}/{tot}')

    check(all(p.get('ok') and p.get('overlay') for s in stus for p in s['pages']),
          '每一面都识别成功且校对图落盘',
          str([(s['sid'], [p.get('overlay') for p in s['pages']]) for s in stus]))
    pid = next(p['id'] for s in stus for p in s['pages'] if p.get('id'))
    st, png = req('GET', f'/api/overlay/{pid}.png', raw=True)
    check(st == 200 and png[:8] == b'\x89PNG\r\n\x1a\n', '批量结果的校对图可取',
          f'HTTP {st}, {len(png)} bytes')

    print('\n=== F. 批量结果的统计与导出（带考号/姓名/班级）===')
    st, sm = req('POST', '/api/stats', json_body={'key': key})
    check(st == 200, '不带 ids 时统计默认针对最近一批', f'HTTP {st}')
    check(sm.get('sheetCount') == 4, '统计覆盖 4 位考生（没有混进前面单张的 12 份）',
          f"实测 {sm.get('sheetCount')}")
    names = [x['name'] for x in (sm.get('sheets') or [])]
    check(any('张伟明' in n for n in names), '统计里带上了姓名', str(names[:2]))
    check(next(x for x in sm['sheets'] if '张伟明' in x['name'])['score'] == 19,
          '张伟明（就是 s01）满分 19/19',
          next(x for x in sm['sheets'] if '张伟明' in x['name']))

    st, csv_text = req('POST', '/api/export.csv', fields={'key': key}, raw=True)
    lines = [l for l in csv_text.decode('utf-8-sig').strip().splitlines() if l.strip()]
    check(lines[0].startswith('考号,姓名,班级,文件,1,2,'), 'CSV 表头带考号/姓名/班级',
          lines[0][:80])
    check(len(lines) == 5, 'CSV = 表头 + 4 位考生', f'实测 {len(lines)}')
    check(lines[1].startswith('2026010234,张伟明,高三(12)班') and lines[1].endswith(',19'),
          '首行是考号最小的那位且得分正确', lines[1][:60] + ' … ' + lines[1][-8:])

    print('\n=== G. 人工补录 / 名单单独导入 ===')
    st, j2 = req('POST', '/api/batch/rematch',
                 fields={'overrides': json.dumps({'2026010237': {'name': '补录同学',
                                                                 'cls': '高三(12)班'}})})
    check(st == 200, '重新套名单 200', f'HTTP {st}')
    fixed = next((s for s in (j2.get('students') or []) if s['sid'] == '2026010237'), {})
    check(fixed.get('name') == '补录同学' and fixed.get('manual') is True,
          '人工补录生效且标记 manual', str(fixed.get('name')))
    check(fixed.get('matched') is True and not (fixed.get('issues') or []),
          '补录后视为已确认、问题项清空（manual 标记让界面能区分来源）',
          str(fixed.get('issues')))
    check('不在名单里' not in ' | '.join(j2.get('warnings') or []),
          '补录之后「有考号不在名单里」的警告随之消失',
          ' | '.join(j2.get('warnings') or [])[:100])
    check(fixed.get('answers'), '补录后识别出来的答案没被动过',
          str(len(fixed.get('answers') or {})))

    st, j3 = req('POST', '/api/roster',
                 files=[('file', '名单.csv', ROSTER.encode('utf-8'), 'text/csv')])
    check(st == 200 and (j3.get('roster') or {}).get('count') == 4,
          '名单可单独导入并重新套用', str(j3.get('roster')))

    st, rc = req('GET', '/api/roster.csv', raw=True)
    rl = [l for l in rc.decode('utf-8-sig').strip().splitlines() if l.strip()]
    check(rl[0] == '考号,姓名,班级,页数,备注', '名单对账表头正确', rl[0])
    check(len(rl) == 5, '名单对账 4 人', f'实测 {len(rl)}')

    print('\n=== H. 页序越界必须报错（不能静默夹到最后一页）===')
    # 模板只有 1 面；给同一考号两张图 → 第二张会被排成第 2 面
    zip_over = make_zip([
        ('2026010234/正面.png', img('s01.png')),
        ('2026010234/反面.png', img('s02.png')),
    ])
    j4 = post_zip('H. 多传了一页', zip_over)
    s4 = (j4.get('students') or [{}])[0]
    pgs = s4.get('pages') or []
    check(len(pgs) == 2, '两面都被列出（而不是悄悄少一面）', f'实测 {len(pgs)}')
    check(sum(1 for p in pgs if p.get('ok')) == 1, '只有第 1 面识别成功', str([p.get('ok') for p in pgs]))
    bad = next((p for p in pgs if not p.get('ok')), {})
    check('超出模板范围' in str(bad.get('error')),
          '越界那一面明确报「超出模板范围」', str(bad.get('error'))[:110])
    check(any('超出模板范围' in i for i in (s4.get('issues') or [])),
          '问题进到考生的待确认队列', str(s4.get('issues'))[:140])
    check(len(s4.get('answers') or {}) == 20, '第 1 面的答案仍然保留（不因一面出错整份作废）',
          str(len(s4.get('answers') or {})))

    print('\n=== I. 整个文件夹上传（webkitRelativePath → paths 字段）===')
    # 浏览器选文件夹时，每个文件都带 webkitRelativePath；服务端靠 paths 还原目录结构
    st, j5 = req('POST', '/api/batch',
                 fields=[('pxPerMm', '8.0'), ('paths', '一班/2026010234/正面.png'),
                         ('paths', '一班/2026010235/正面.png')],
                 files=[('files', '正面.png', img('s01.png'), 'image/png'),
                        ('files', '正面.png', img('s02.png'), 'image/png')])
    check(st == 200, '文件夹上传 200', f'HTTP {st} {str(j5)[:160]}')
    fs = j5.get('students') or []
    check([s['sid'] for s in fs] == ['2026010234', '2026010235'],
          '两张同名文件靠目录名区分成两位考生', str([s['sid'] for s in fs]))
    check(all(p.get('ok') for s in fs for p in s['pages']), '两面都识别成功')
    check(all('一班/202601023' in (p.get('source') or '') for s in fs for p in s['pages']),
          '保留原始相对路径便于溯源', str([p.get('source') for s in fs for p in s['pages']]))

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
