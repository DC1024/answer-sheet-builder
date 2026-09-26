# 回归：_qnos 在没有模板、且调用方没传结果（[]）时，
# 必须退回库里已存的学生答案题号，否则工作台弹窗逐题编辑区会整片空白。
# （2026-09-26 真实浏览器 E2E 抓出：无模板考试的工作台弹窗一题都渲染不出来。）
import os
import sys
import tempfile

SCN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCN)

from app import store as store_mod, server as server_mod

fails = 0
def ok(c, m):
    print(('  ✅ ' if c else '  ❌ ') + m)
    global fails
    if not c: fails += 1

def main():
    db = os.path.join(tempfile.mkdtemp(), 'asb.db')
    STORE = store_mod.Store(db)
    server_mod.STORE = STORE            # _qnos 读模块级 STORE
    exam = STORE.create_exam('t')
    STORE.save_students(exam['id'], [
        {'sid': '1', 'answers': {1: {'answer': 'A', 'by': 'rule'},
                                 2: {'answer': 'B', 'by': 'cnn'}},
         'fixes': {}, 'grading': {}},
    ])

    # 1) 没有模板、传入空结果 → 必须退回学生答案题号
    e = STORE.exam(exam['id'])
    qnos = server_mod._qnos(e, [])
    ok(qnos == [1, 2], '无模板 + 空结果：_qnos 回退到学生题号 -> ' + str(qnos))

    # 2) 有模板时仍以模板为权威（含学生没填的题）
    STORE.set_template(exam['id'],
                       {'pages': [{'questions': [{'no': 1}, {'no': 2}, {'no': 3}]}]}, {})
    e2 = STORE.exam(exam['id'])
    qnos2 = server_mod._qnos(e2, [])
    ok(qnos2 == [1, 2, 3], '有模板：_qnos 取模板题号（含未填题）-> ' + str(qnos2))

    print('🎉 _qnos 回退逻辑全部通过' if fails == 0 else '❌ 有失败')
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main()
