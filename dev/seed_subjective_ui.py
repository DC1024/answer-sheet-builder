# 主观题阅卷工作台的 UI 联调种子：造一份带主观题的考试（含已识别卷子），
# 然后就地起真 Flask 服务，交给 dev/verify_subjective_ui.cjs 用 playwright 点。
#
# 为什么不在 node 里顺手把服务起起来：**本机沙箱里 node 起不了任何子进程**
# （execFileSync 连 cmd.exe 都 EBUSY），所以「起服务」这一步必须由外面的 shell 做。
# 拆成「py 起服务 → node 点页面」两个进程，才是真跑，而不是假装跑过。
#
# 用法：
#   scanner/.venv/Scripts/python.exe dev/seed_subjective_ui.py
#   环境变量：PORT（默认 8199）、ASB_DATA / ASB_DB（默认落 dev/.cache/ui-data）
import io
import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scanner'))

CACHE = os.path.join(HERE, '.cache')
os.makedirs(CACHE, exist_ok=True)

# 每次跑都开一个新目录，绝不删旧的 —— 「第一次打开页面」的状态必须可复现，
# 但就地清空一个数据目录在沙箱里会触发批量删除保护（而且真删错了没法救）。
# dev/.cache 本身在 .gitignore 里，攒几个不碍事。
DATA = os.environ.get('ASB_DATA') or tempfile.mkdtemp(prefix='ui-data-', dir=CACHE)
PORT = int(os.environ.get('PORT') or 8199)

os.makedirs(DATA, exist_ok=True)
os.environ['ASB_DATA'] = DATA
os.environ['ASB_DB'] = os.path.join(DATA, 'asb.db')

from app import server                                                        # noqa: E402

FIX = os.path.join(ROOT, 'scanner', 'tests', 'fixtures')
USER, PW = 'uiadmin', 'uitest12345'


def b(name):
    with open(os.path.join(FIX, name), 'rb') as f:
        return f.read()


def mkzip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for nm, data in entries:
            zf.writestr(nm, data)
    return buf.getvalue()


# 和第 21/22 题的区域：21 题盖住首行填涂圈（裁剪图上一定有墨迹，肉眼能看出裁对了），
# 22 题落在空白区（够大，好核对尺寸）。这两个坐标跟 tests/test_subjective.py 保持一致 ——
# 那边验的是后端，这边验的是「后端的东西在页面上长什么样」，用同一份数据才有意义。
SUB_A = {'x': 107.5, 'y': 111.0, 'w': 185.0, 'h': 8.0}
SUB_B = {'x': 105.0, 'y': 200.0, 'w': 180.0, 'h': 30.0}


def subjective_template():
    with open(os.path.join(FIX, 'template.json'), encoding='utf-8') as f:
        t = json.load(f)
    t['questionCount'] = 22
    t['pages'][0]['questions'] += [
        {'no': 21, 'x': SUB_A['x'], 'y': SUB_A['y'], 'region': SUB_A,
         'points': 10.0, 'subs': [{'label': '第(1)问 求导', 'points': 4.0},
                                  {'label': '第(2)问 讨论单调性', 'points': 6.0}]},
        {'no': 22, 'x': SUB_B['x'], 'y': SUB_B['y'], 'region': SUB_B, 'points': 6.0},
    ]
    return json.dumps(t, ensure_ascii=False).encode('utf-8')


ROSTER = ('考号,姓名,班级\n'
          '2026010234,张伟明,高三(12)班\n'
          '2026010235,李思,高三(12)班\n'
          '2026010236,王大雨,高三(12)班\n')


def main():
    c = server.app.test_client()

    r = c.post('/api/setup', json={'username': USER, 'password': PW})
    assert r.status_code == 200, r.data[:200]
    r = c.post('/api/login', json={'username': USER, 'password': PW})
    assert r.status_code == 200, r.data[:200]

    r = c.post('/api/template',
               data={'file': (io.BytesIO(subjective_template()), 'template.json')},
               content_type='multipart/form-data')
    assert r.status_code == 200, r.data[:300]
    subj = ((r.get_json() or {}).get('summary') or {}).get('subjective') or {}
    assert sorted(subj, key=int) == ['21', '22'], subj

    # 单张扫一遍拿到 s01 的真实答案当标准答案（客观分才是个确定的数，不是靠猜）
    r = c.post('/api/scan', data={'files': (io.BytesIO(b('s01.png')), 's01.png'), 'page': '0'},
               content_type='multipart/form-data')
    res = ((r.get_json() or {}).get('results') or [{}])[0]
    region_rid = res.get('id')
    keymap = {q['no']: q['answer'] for q in res.get('questions') or []
              if q['no'] <= 20 and q.get('answer')}
    key = ' '.join(f'{k}{v}' for k, v in sorted(keymap.items()))
    r = c.post('/api/answer-key', json={'key': key})
    assert r.status_code == 200, r.data[:200]

    # 批量传一个班：工作台列表要有好几个人，才看得出「客观/主观/总分」三列。
    # 名单里 3 个人，但只有 2 张卷子 —— 缺考的那位正好验证「没扫到的怎么显示」。
    z = mkzip([
        ('高三12班/2026010234/正面.png', b('s01.png')),
        ('高三12班/2026010235/正面.png', b('s02.png')),
        ('高三12班/名单.csv', ROSTER.encode('utf-8')),
    ])
    r = c.post('/api/batch', data={'files': (io.BytesIO(z), '高三12班.zip')},
               content_type='multipart/form-data')
    assert r.status_code == 200, r.data[:300]
    students = (r.get_json() or {}).get('students') or []
    assert len(students) == 2, students

    gj = c.get('/api/gradebook').get_json() or {}
    mx = gj.get('max') or {}
    print(json.dumps({'ok': True, 'data': DATA, 'template': os.path.join(DATA, 'ui.exam'),
                      'students': [s['sid'] for s in students], 'max': mx,
                      'subjective': sorted((gj.get('subjective') or {}), key=int),
                      'regionRid': region_rid, 'objMax': len(keymap)},
                     ensure_ascii=False))
    sys.stdout.flush()

    server.app.run(host='127.0.0.1', port=PORT, threaded=True, debug=False,
                   use_reloader=False)


if __name__ == '__main__':
    main()
