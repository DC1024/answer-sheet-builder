# -*- coding: utf-8 -*-
"""手写（或印刷）A-D 字母的小 CNN 5-fold 交叉验证。

用法示例（用现有印刷体字母做 pipeline 冒烟）：
  python tools/train_cnn_cv.py --dataset tests/fixtures/real30/letters

真实手写样本导出后：
  python tools/train_cnn_cv.py --dataset tests/fixtures/real30/handwritten

关键设计：
- 按 sheet 做 GroupKFold，避免同一份卷子的字形同时出现在训练/测试集。
- 输入保持 48x48（与 hwletter.extract_glyph 输出一致），不归到 28x28 以免丢失细节。
- 数据增广默认较激进，模拟真实手写里的断笔、开环、倾斜、大小不一。
- 同时报告现有 OpenCV 特征分类器在同一批字形上的准确率，便于对比。
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np
import cv2

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, Subset
from sklearn.model_selection import GroupKFold

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from app import hwletter  # noqa: E402

LET = ['A', 'B', 'C', 'D']
LBL2I = {c: i for i, c in enumerate(LET)}


class GlyphDataset(Dataset):
    """48x48 二值字形 → float32 张量 [1,48,48]；墨=1，背景=0。"""
    def __init__(self, manifest, root, augment=False, heavy=False):
        self.samples = manifest
        self.root = root
        self.augment = augment
        self.heavy = heavy

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        item = self.samples[idx]
        path = os.path.join(self.root, item['file'])
        im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if im is None:
            raise FileNotFoundError(path)
        # 缩放到 48x48（已经是 48x48，但保险）
        if im.shape != (48, 48):
            im = cv2.resize(im, (48, 48), interpolation=cv2.INTER_AREA)
        x = im.astype(np.float32) / 255.0
        x = x[None, ...]  # 1,H,W

        if self.augment:
            x = self._aug(x)
        return torch.from_numpy(x), LBL2I[item['label']]

    def _aug(self, x):
        # x: numpy [1,H,W]
        # 随机旋转 ±18°
        angle = np.random.uniform(-18, 18)
        h, w = x.shape[1:]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        r = cv2.warpAffine(x[0], M, (w, h), borderValue=0.0)

        # 随机仿射：平移 10%、缩放 0.82~1.18、剪切 ±12°
        tx = np.random.uniform(-0.10, 0.10) * w
        ty = np.random.uniform(-0.10, 0.10) * h
        scale = np.random.uniform(0.82, 1.18)
        shear = np.random.uniform(-12, 12)
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 0, scale)
        M[0, 2] += tx
        M[1, 2] += ty
        # 简单加入 shear
        M = np.vstack([M, [0, 0, 1]])
        shear_mx = np.array([[1.0, np.tan(np.radians(shear)), 0],
                             [0.0, 1.0, 0]], dtype=np.float32)
        r = cv2.warpAffine(r, shear_mx, (w, h), borderValue=0.0)
        r = cv2.warpAffine(r, M[:2], (w, h), borderValue=0.0)

        # 加少量高斯噪声 / 椒盐噪声
        noise = np.random.normal(0, 0.03, r.shape).astype(np.float32)
        r = np.clip(r + noise, 0, 1)
        if np.random.rand() < 0.1:
            salt = np.random.rand(*r.shape) < 0.005
            r[salt] = 1.0

        # 模拟"开环/断笔"：小概率用形态学开运算打断细桥
        if self.heavy and np.random.rand() < 0.2:
            r_u8 = (r * 255).astype(np.uint8)
            k = np.random.choice([2, 3])
            r_u8 = cv2.erode(r_u8, np.ones((k, k), np.uint8), iterations=1)
            r = r_u8.astype(np.float32) / 255.0

        return r[None, ...]


class SmallCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.Conv2d(32, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Dropout(0.25),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
            nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Dropout(0.25),
        )
        self.classifier = nn.Sequential(
            nn.Linear(64 * 12 * 12, 256), nn.ReLU(), nn.Dropout(0.5),
            nn.Linear(256, 4),
        )

    def forward(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        return self.classifier(x)


def opencv_baseline(dataset):
    """用当前 hwletter.classify() 对 dataset 里每个字形做预测，返回准确率。"""
    correct = total = 0
    for item in dataset.samples:
        path = os.path.join(dataset.root, item['file'])
        im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        if im.shape != (48, 48):
            im = cv2.resize(im, (48, 48), interpolation=cv2.INTER_AREA)
        r = hwletter.classify(im)
        if r is None:
            continue
        total += 1
        if r['letter'] == item['label']:
            correct += 1
    if total == 0:
        return 0.0, 0
    return correct / total, total


def train_one_fold(train_ds, val_ds, epochs=60, lr=1e-3, batch=32, heavy_aug=False):
    device = torch.device('cpu')
    train_ds.augment = True
    train_ds.heavy = heavy_aug
    val_ds.augment = False
    train_dl = DataLoader(train_ds, batch_size=batch, shuffle=True, drop_last=False)
    val_dl = DataLoader(val_ds, batch_size=batch, shuffle=False)

    model = SmallCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    crit = nn.CrossEntropyLoss()
    best_state, best_val = None, float('inf')
    no_improve = 0
    for ep in range(1, epochs + 1):
        model.train()
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            out = model(x)
            loss = crit(out, y)
            loss.backward()
            opt.step()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x, y in val_dl:
                x, y = x.to(device), y.to(device)
                out = model(x)
                val_loss += F.cross_entropy(out, y, reduction='sum').item()
        val_loss /= len(val_ds)
        if val_loss < best_val - 1e-4:
            best_val = val_loss
            best_state = model.state_dict()
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= 12:   # early stopping
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def evaluate(model, dataset, batch=64):
    model.eval()
    dl = DataLoader(dataset, batch_size=batch, shuffle=False)
    all_y, all_pred, all_conf = [], [], []
    with torch.no_grad():
        for x, y in dl:
            out = model(x)
            prob = F.softmax(out, dim=1)
            conf, pred = prob.max(dim=1)
            all_y.extend(y.numpy())
            all_pred.extend(pred.numpy())
            all_conf.extend(conf.numpy())
    return np.array(all_y), np.array(all_pred), np.array(all_conf)


def main():
    ap = argparse.ArgumentParser(description='A-D 字形 CNN 5-fold 交叉验证')
    ap.add_argument('--dataset', required=True, help='数据集根目录（含 manifest.json 和 A/B/C/D 子目录）')
    ap.add_argument('--epochs', type=int, default=60)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--batch', type=int, default=32)
    ap.add_argument('--heavy-aug', action='store_true', help=' heavier augmentation（手写场景建议开启）')
    ap.add_argument('--no-opencv', action='store_true', help='不跑 OpenCV 基线')
    a = ap.parse_args()

    root = a.dataset
    manifest = json.load(open(os.path.join(root, 'manifest.json'), encoding='utf-8'))
    print(f'加载样本 {len(manifest)} 个')
    print('类别分布:', Counter(s['label'] for s in manifest))

    full_ds = GlyphDataset(manifest, root, augment=False)
    groups = np.array([int(s['sheet']) for s in manifest])
    y = np.array([LBL2I[s['label']] for s in manifest])

    if not a.no_opencv:
        oc_acc, oc_n = opencv_baseline(full_ds)
        print(f'\nOpenCV 特征分类器基线（同批字形）: {oc_acc * 100:.1f}% ({oc_n}/{len(manifest)})')

    print('\n开始 5-fold 按卷交叉验证 ...')
    gkf = GroupKFold(n_splits=5)
    fold_accs = []
    cm = Counter()
    fold_details = []
    all_y_true, all_y_pred, all_conf = [], [], []
    for fold, (tr_idx, te_idx) in enumerate(gkf.split(np.zeros(len(manifest)), y, groups), 1):
        train_ds = GlyphDataset([manifest[i] for i in tr_idx], root, augment=False)
        test_ds = GlyphDataset([manifest[i] for i in te_idx], root, augment=False)
        model = train_one_fold(train_ds, test_ds, epochs=a.epochs, lr=a.lr, batch=a.batch,
                               heavy_aug=a.heavy_aug)
        y_true, y_pred, conf = evaluate(model, test_ds)
        acc = (y_true == y_pred).mean()
        fold_accs.append(acc)
        all_y_true.append(y_true)
        all_y_pred.append(y_pred)
        all_conf.append(conf)
        for t, p in zip(y_true, y_pred):
            cm[(LET[t], LET[p])] += 1
        fold_details.append({
            'fold': fold,
            'train_sheets': sorted(set(int(groups[i]) for i in tr_idx)),
            'test_sheets': sorted(set(int(groups[i]) for i in te_idx)),
            'n_test': int(len(te_idx)),
            'accuracy': round(float(acc), 4),
        })
        print(f'  fold {fold}: test={len(te_idx)} acc={acc * 100:.1f}%')

    all_y_true = np.concatenate(all_y_true)
    all_y_pred = np.concatenate(all_y_pred)
    all_conf = np.concatenate(all_conf)

    print('\n-- 汇总 --')
    print(f'每折准确率: {[f"{x*100:.1f}%" for x in fold_accs]}')
    print(f'平均 ± 标准差: {np.mean(fold_accs)*100:.1f}% ± {np.std(fold_accs)*100:.1f}%')
    print('\n-- 混淆矩阵（行=真值，列=CNN预测）--')
    print('      ' + ''.join(f'{c:>6}' for c in LET))
    for c in LET:
        row = [cm[(c, g)] for g in LET]
        print(f'  {c}    ' + ''.join(f'{v:>6}' for v in row) + f'  {sum(row):>5}')

    # 用最大 softmax 概率作为置信度，给出"自动阅卷 vs 复核"权衡
    print('\n-- 自动阅卷精度 vs 人工复核量（按 CNN 置信度）--')
    print(f'{"conf_thr":>10} {"自动判":>8} {"自动准确率":>10} {"复核":>8} {"复核量":>10}')
    total = len(all_y_true)
    for thr in (0.50, 0.70, 0.80, 0.90, 0.95, 0.99):
        mask = all_conf >= thr
        n_auto = int(mask.sum())
        n_review = total - n_auto
        auto_acc = (all_y_true[mask] == all_y_pred[mask]).mean() if n_auto else 0.0
        print(f'{thr:>10.2f} {n_auto:>8} {auto_acc*100:>9.1f}% {n_review:>8} '
              f'{n_review/total*100:>9.1f}%')

    # 输出折明细 JSON
    out_json = os.path.join(root, 'cnn_cv_result.json')
    with open(out_json, 'w', encoding='utf-8') as fh:
        json.dump({
            'dataset': root,
            'n_samples': len(manifest),
            'opencv_baseline': {'accuracy': round(oc_acc, 4), 'n_evaluated': oc_n} if not a.no_opencv else None,
            'folds': fold_details,
            'mean_accuracy': round(float(np.mean(fold_accs)), 4),
            'std_accuracy': round(float(np.std(fold_accs)), 4),
            'confusion_matrix': {f'{t}->{p}': n for (t, p), n in cm.items()},
        }, fh, ensure_ascii=False, indent=2)
    print(f'\n结果保存: {out_json}')


if __name__ == '__main__':
    main()
