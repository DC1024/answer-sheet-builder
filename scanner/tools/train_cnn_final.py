# -*- coding: utf-8 -*-
"""用全部真实手写字形训练最终 SmallCNN 并保存权重。

与 train_cnn_cv.py 同架构（取自 app.cnn_letter._build_model），同预处理。
按 9:1 分层抽样出验证集做 early stopping，最佳 epoch 权重保存为 app/hwletter_cnn.pt。

用法：python tools/train_cnn_final.py [--epochs 200] [--heavy-aug]
"""
import argparse
import json
import os
import sys
from collections import Counter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

# 复用训练脚本里的 GlyphDataset（含与推理完全一致的预处理 + 增广）
from train_cnn_cv import GlyphDataset  # noqa: E402
from app.cnn_letter import _build_model, classify_glyph  # noqa: E402

LET = ['A', 'B', 'C', 'D']
LBL2I = {c: i for i, c in enumerate(LET)}


def main():
    ap = argparse.ArgumentParser(description='训练最终手写 A-D CNN 并保存权重')
    ap.add_argument('--dataset', default=os.path.join(HERE, '..', 'tests', 'fixtures', 'real30', 'handwritten'))
    ap.add_argument('--epochs', type=int, default=200)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--batch', type=int, default=32)
    ap.add_argument('--heavy-aug', action='store_true', help='更激进增广（手写建议开）')
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'app', 'hwletter_cnn.pt'))
    a = ap.parse_args()

    root = a.dataset
    manifest = json.load(open(os.path.join(root, 'manifest.json'), encoding='utf-8'))
    print('样本', len(manifest), '类别', dict(Counter(s['label'] for s in manifest)))

    SmallCNN = _build_model()
    y = np.array([LBL2I[s['label']] for s in manifest])

    # 分层抽样 90/10 出验证集（按类别等比例，每类至少留 1）
    rng = np.random.RandomState(42)
    idx = np.arange(len(manifest))
    train_idx, val_idx = [], []
    for c in range(4):
        ci = idx[y[idx] == c]
        rng.shuffle(ci)
        n = max(1, int(round(len(ci) * 0.1)))
        val_idx.extend(ci[:n])
        train_idx.extend(ci[n:])
    rng.shuffle(train_idx)

    train_ds = GlyphDataset([manifest[i] for i in train_idx], root, augment=False)
    val_ds = GlyphDataset([manifest[i] for i in val_idx], root, augment=False)
    train_ds.augment, train_ds.heavy = True, a.heavy_aug
    train_dl = DataLoader(train_ds, batch_size=a.batch, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=a.batch, shuffle=False)

    dev = torch.device('cpu')
    model = SmallCNN().to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=a.lr, weight_decay=1e-4)
    crit = nn.CrossEntropyLoss()

    best_val, best_state, best_acc, no_imp = float('inf'), None, 0.0, 0
    for ep in range(1, a.epochs + 1):
        model.train()
        for x, yb in train_dl:
            x, yb = x.to(dev), yb.to(dev)
            opt.zero_grad()
            loss = crit(model(x), yb)
            loss.backward()
            opt.step()
        model.eval()
        vl, correct, total = 0.0, 0, 0
        with torch.no_grad():
            for x, yb in val_dl:
                x, yb = x.to(dev), yb.to(dev)
                out = model(x)
                vl += F.cross_entropy(out, yb, reduction='sum').item()
                correct += int((out.argmax(1) == yb).sum())
                total += len(yb)
        vl /= total
        acc = correct / total
        if vl < best_val - 1e-4:
            best_val, best_state = vl, {k: v.cpu().clone() for k, v in model.state_dict().items()}
            best_acc, no_imp = acc, 0
        else:
            no_imp += 1
            if no_imp >= 20:
                print(f'  early stop @ epoch {ep}')
                break

    if best_state is None:
        best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    torch.save(best_state, a.out)
    print(f'保存权重 → {a.out}  (验证集最佳 acc={best_acc * 100:.1f}%)')

    # 全量复测（含训练样本，仅供 sanity；诚实泛化率见 5-fold CV 的 97.6%）
    all_ds = GlyphDataset(manifest, root, augment=False)
    al = DataLoader(all_ds, batch_size=64, shuffle=False)
    model.eval()
    cor, tot = 0, 0
    with torch.no_grad():
        for x, yb in al:
            x, yb = x.to(dev), yb.to(dev)
            cor += int((model(x).argmax(1) == yb).sum())
            tot += len(yb)
    print(f'全量复测 acc={cor / tot * 100:.1f}% ({cor}/{tot})')


if __name__ == '__main__':
    main()
