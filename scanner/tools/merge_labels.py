# -*- coding: utf-8 -*-
"""把校对导出的 labels_31_60.json（id->字母）并入 expected.json（31–60 段）。

labels_31_60.json 由 review_31_60.html 导出，格式 {"31_01":"A", ...}。
本脚本只新增 31–60，不动 01–30（填涂版）。缺失条目保持未标注，
后续 extract_handwritten.py 会自动跳过未标注题，不会污染训练集。

用法：python tools/merge_labels.py <labels_31_60.json>
"""
import os
import sys
import json
import glob


def main():
    if len(sys.argv) < 2:
        print('用法: python tools/merge_labels.py <labels_31_60.json>')
        return
    labels_path = sys.argv[1]
    HERE = os.path.dirname(os.path.abspath(__file__))
    FIX = os.path.join(HERE, '..', 'tests', 'fixtures', 'real30')
    exp_path = os.path.join(FIX, 'expected.json')

    labels = json.load(open(labels_path, encoding='utf-8'))
    exp = json.load(open(exp_path, encoding='utf-8'))
    sheets = exp.setdefault('sheets', {})

    # 用文件名反查每卷姓名（labels 文件不含姓名）
    name_map = {}
    for f in glob.glob(os.path.join(FIX, '第*.png')):
        base = os.path.basename(f)
        key = base.split('_')[0].replace('第', '').replace('份', '')
        nm = base.split('_')[1] if '_' in base else ''
        name_map[key] = nm

    added = 0
    bad = 0
    for sid, letter in labels.items():
        if '_' not in sid:
            bad += 1
            continue
        sheet, q = sid.split('_', 1)
        if letter not in 'ABCD':
            bad += 1
            continue
        if sheet not in sheets:
            sheets[sheet] = {'name': name_map.get(sheet, sheet), 'answers': {}}
        if 'answers' not in sheets[sheet]:
            sheets[sheet]['answers'] = {}
        sheets[sheet]['answers'][str(int(q))] = letter
        added += 1

    json.dump(exp, open(exp_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 统计 31–60 覆盖
    cov = {}
    total = 0
    for s in range(31, 61):
        ks = str(s)
        n = len(sheets.get(ks, {}).get('answers', {}))
        cov[ks] = n
        total += n
    print(f'[合并] 新增标注 {added} 个，跳过非法/缺字段 {bad} 个')
    print(f'[覆盖] 31–60 共 {total} / 300 题有真值；'
          f'缺失卷/题：', end='')
    miss = [f'{k}({10-cov[k]})' for k in cov if cov[k] < 10]
    print(','.join(miss) if miss else '无')


if __name__ == '__main__':
    main()
