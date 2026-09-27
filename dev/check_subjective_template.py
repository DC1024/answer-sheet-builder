# 端到端验证（第 2 步，扫描端）：解析 dev/verify_subjective.cjs 导出的制卡端模板。
#
#   scanner/.venv/Scripts/python.exe dev/check_subjective_template.py
#
# 与 dev/verify_subjective.cjs 是一对：那一步在真实浏览器里配好「人工阅卷」并导出模板，
# 这一步把同一份模板喂给扫描端的 omr，确认两边对「哪些题要人工阅卷、满分多少、
# 小问怎么分、作答区在哪」的理解**完全一致**。
#
# 为什么拆成两步：node 起子进程在本机沙箱里会 EBUSY（连 cmd.exe 都起不来），
# 写成一个脚本会在沙箱里变成「看起来跑了其实没跑」的假绿。
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scanner'))

from app import omr                                                     # noqa: E402

TPL = os.environ.get('OUT') or os.path.join(HERE, '.cache', 'subjective_template.json')
FAILS = []


def ok(cond, label, extra=''):
    print(('  ✅ ' if cond else '  ❌ ') + label + (f'  {extra}' if extra else ''))
    if not cond:
        FAILS.append(label)


def eq(got, want, label):
    ok(got == want, label, f'（期望 {want!r}，实测 {got!r}）')


if not os.path.exists(TPL):
    print('❌ 找不到模板文件：%s' % TPL)
    print('   请先跑：NODE_PATH=<node_modules> node dev/verify_subjective.cjs')
    sys.exit(1)

tpl = omr.load_template(open(TPL, encoding='utf-8').read())
subj = omr.subjective_map(tpl)
print('模板：%s，主观题 %s' % (tpl.get('format'), sorted(subj, key=int)))

print('=== 扫描端解析制卡端导出的模板 ===')
eq(sorted(subj, key=int), [7, 9], '认出的主观题与制卡端一致（只有第 7、9 题）')
eq(subj[7]['points'], 7.0, '第 7 题满分 7（= 小问之和，制卡端只给了小问没给整题）')
eq([s['points'] for s in subj[7]['subs']], [3.0, 4.0], '第 7 题的逐小问满分 3/4')
ok(all(s['label'] for s in subj[7]['subs']), '小问名用自动编号补齐（阅卷界面要显示）',
   str([s['label'] for s in subj[7]['subs']]))
eq(subj[9]['points'], 10.0, '第 9 题满分 10')
eq([s['points'] for s in subj[9]['subs']], [4.0, 6.0], '第 9 题的逐小问满分 4/6')
eq(subj[7]['page'], 0, '记下在第几面（前端据此找裁剪图）')
ok(subj[7]['region'] and subj[7]['region']['w'] > 3 and subj[7]['region']['h'] > 3,
   '第 7 题作答区坐标完整', json.dumps(subj[7]['region'], ensure_ascii=False))
ok(subj[9]['region'] and subj[9]['region']['h'] > 100,
   '第 9 题（解答题）区域是「整题一块」，够高', json.dumps(subj[9]['region'], ensure_ascii=False))
ok(all('region' not in q for p in tpl['pages'] for q in (p.get('questions') or [])
       if q.get('no', 0) <= 6),
   '没勾「人工阅卷」的题在模板里不带 region（前 6 道选择题）')

# 满分统计口径：客观 6 题各 1 分 + 主观 17 分
mx = omr.template_summary(tpl)
eq(sorted((mx.get('subjective') or {}), key=int), [7, 9], '模板摘要里的主观题也是这两道')
eq(sum(v['points'] for v in (mx.get('subjective') or {}).values()), 17.0,
   '主观题满分合计 17（7 + 10）')

print()
if FAILS:
    print(f'⚠️  {len(FAILS)} 项未通过：')
    for f in FAILS:
        print('   -', f)
    sys.exit(1)
print('🎉 扫描端解析制卡端模板 全部通过')
