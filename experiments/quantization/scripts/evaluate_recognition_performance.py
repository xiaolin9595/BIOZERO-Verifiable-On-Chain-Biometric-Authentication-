#!/usr/bin/env python3
"""
人脸识别性能评估：量化前后对比

评估指标：
- Precision (精确度)
- Recall (召回率)
- F1-Score
- Accuracy (准确率)
- TPR (True Positive Rate)
- FPR (False Positive Rate)
- EER (Equal Error Rate)
- ROC-AUC

在不同阈值下测试量化对识别性能的影响
"""

import sys
sys.path.append('biozero_quantization_experiment/scripts')

import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
import numpy as np
from PIL import Image
from pathlib import Path
import json
from datetime import datetime
from pedersen_quantizers import (
    AsymmetricQuantizer,
    euclidean_distance
)
from sklearn.metrics import (
    precision_score, recall_score, f1_score, accuracy_score,
    roc_curve, auc, confusion_matrix
)
import matplotlib.pyplot as plt
from itertools import combinations


def load_facenet_model(device):
    """加载 FaceNet 模型"""
    print("[模型加载] FaceNet InceptionResnetV1...")
    mtcnn = MTCNN(image_size=160, margin=14, device=device)
    resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
    print("✓ 模型加载完成\n")
    return mtcnn, resnet


def extract_embeddings_from_dataset(mtcnn, resnet, image_dir, device, max_identities=None):
    """
    从数据集提取特征向量

    Args:
        max_identities: 最大身份数量限制（None表示无限制）

    Returns:
        embeddings: numpy array (N, 512)
        labels: list of identity labels
        image_paths: list of image file paths
    """
    print(f"[特征提取] 从 {image_dir} 提取...")

    embeddings = []
    labels = []
    image_paths = []

    person_dirs = sorted([d for d in Path(image_dir).iterdir()
                         if d.is_dir() and not d.name.startswith('.')])

    # 限制身份数量
    if max_identities:
        person_dirs = person_dirs[:max_identities]

    total_identities = len(person_dirs)

    for idx, person_dir in enumerate(person_dirs, 1):
        person_label = person_dir.name
        identity_count = 0

        for img_file in sorted(person_dir.glob("*.jpg")):
            if not img_file.name.startswith('._'):
                try:
                    img = Image.open(img_file)
                    img_cropped = mtcnn(img)

                    if img_cropped is not None:
                        with torch.no_grad():
                            embedding = resnet(img_cropped.unsqueeze(0)).cpu().numpy()[0]
                            embeddings.append(embedding)
                            labels.append(person_label)
                            image_paths.append(str(img_file))
                            identity_count += 1
                except Exception as e:
                    print(f"  ✗ 错误: {img_file.name} - {e}")

        # 每处理完一个身份，打印进度
        print(f"  [{idx}/{total_identities}] {person_label}: {identity_count} 张图片")

    embeddings = np.array(embeddings)
    print(f"\n✓ 提取完成: {len(embeddings)} 个样本, {len(set(labels))} 个身份\n")

    return embeddings, labels, image_paths


def generate_pairs_and_labels(embeddings, labels):
    """
    生成所有可能的图像对及其真实标签

    Returns:
        pairs: list of (idx1, idx2)
        pair_labels: list of 0/1 (0=不同人, 1=同一人)
    """
    print("[对生成] 生成所有图像对...")

    pairs = []
    pair_labels = []

    n = len(embeddings)

    # 生成所有可能的对
    for i, j in combinations(range(n), 2):
        pairs.append((i, j))
        # 标签: 1=同一人, 0=不同人
        pair_labels.append(1 if labels[i] == labels[j] else 0)

    genuine_pairs = sum(pair_labels)
    impostor_pairs = len(pair_labels) - genuine_pairs

    print(f"  总对数: {len(pairs)}")
    print(f"  正样本对 (同一人): {genuine_pairs}")
    print(f"  负样本对 (不同人): {impostor_pairs}")

    if genuine_pairs > 0:
        print(f"  正负比例: 1:{impostor_pairs/genuine_pairs:.2f}\n")
    else:
        print(f"  ⚠️  警告: 没有正样本对！每个身份只有一张图片。")
        print(f"     建议: 使用每个身份有多张图片的数据集（如LFW）\n")

    return pairs, np.array(pair_labels)


def cosine_distance(emb1, emb2):
    """计算余弦距离 (1 - cosine_similarity)"""
    dot_product = np.dot(emb1, emb2)
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    cosine_sim = dot_product / (norm1 * norm2)
    return 1 - cosine_sim


def compute_distances(embeddings, pairs, metric='euclidean'):
    """
    计算所有对的距离（浮点域）

    Args:
        embeddings: 特征向量数组
        pairs: 图像对索引列表
        metric: 距离度量，'euclidean' 或 'cosine'

    Returns:
        distances: 距离数组
    """
    if metric == 'euclidean':
        distances = np.array([
            euclidean_distance(embeddings[i], embeddings[j])
            for i, j in pairs
        ])
    elif metric == 'cosine':
        distances = np.array([
            cosine_distance(embeddings[i], embeddings[j])
            for i, j in pairs
        ])
    else:
        raise ValueError(f"不支持的距离度量: {metric}")

    return distances


def compute_integer_distances(embeddings_int, pairs, metric='euclidean'):
    """
    计算所有对的距离（整数域）

    Args:
        embeddings_int: 整数特征向量数组
        pairs: 图像对索引列表
        metric: 距离度量，'euclidean' 或 'cosine'

    Returns:
        distances_int: 距离数组
    """
    distances_int = []

    if metric == 'euclidean':
        for i, j in pairs:
            diff = embeddings_int[i].astype(np.int64) - embeddings_int[j].astype(np.int64)
            dist = np.sqrt(np.sum(diff ** 2))
            distances_int.append(dist)
    elif metric == 'cosine':
        for i, j in pairs:
            emb1 = embeddings_int[i].astype(np.float64)
            emb2 = embeddings_int[j].astype(np.float64)
            dot_product = np.dot(emb1, emb2)
            norm1 = np.linalg.norm(emb1)
            norm2 = np.linalg.norm(emb2)
            cosine_sim = dot_product / (norm1 * norm2)
            dist = 1 - cosine_sim
            distances_int.append(dist)
    else:
        raise ValueError(f"不支持的距离度量: {metric}")

    return np.array(distances_int)


def evaluate_at_threshold(distances, labels, threshold):
    """
    在给定阈值下评估性能

    Args:
        distances: 距离数组
        labels: 真实标签 (1=同一人, 0=不同人)
        threshold: 距离阈值

    Returns:
        metrics: dict of performance metrics
    """
    # 预测: 距离 < 阈值 → 同一人 (1)
    predictions = (distances < threshold).astype(int)

    # 混淆矩阵
    cm = confusion_matrix(labels, predictions)

    # 如果没有正样本（所有标签都是0），混淆矩阵只有2个元素
    if len(np.unique(labels)) == 1 and labels[0] == 0:
        # 只有负样本
        tn, fp = cm.ravel()
        fn = tp = 0
    else:
        tn, fp, fn, tp = cm.ravel()

    # 计算各种指标
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    accuracy = (tp + tn) / (tp + tn + fp + fn)

    # TPR (True Positive Rate) = Recall
    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0

    # FPR (False Positive Rate)
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0

    # TNR (True Negative Rate) = Specificity
    tnr = tn / (tn + fp) if (tn + fp) > 0 else 0

    # FNR (False Negative Rate)
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0

    return {
        'threshold': float(threshold),
        'tp': int(tp),
        'fp': int(fp),
        'tn': int(tn),
        'fn': int(fn),
        'precision': float(precision),
        'recall': float(recall),
        'f1_score': float(f1),
        'accuracy': float(accuracy),
        'tpr': float(tpr),
        'fpr': float(fpr),
        'tnr': float(tnr),
        'fnr': float(fnr)
    }


def find_optimal_threshold(distances, labels):
    """找到最优阈值（使F1最大化）"""
    thresholds = np.linspace(distances.min(), distances.max(), 100)
    best_f1 = 0
    best_threshold = 0
    best_metrics = None

    for threshold in thresholds:
        metrics = evaluate_at_threshold(distances, labels, threshold)
        if metrics['f1_score'] > best_f1:
            best_f1 = metrics['f1_score']
            best_threshold = threshold
            best_metrics = metrics

    return best_threshold, best_metrics


def compute_eer(distances, labels):
    """
    计算 EER (Equal Error Rate)
    EER 是 FPR = FNR 时的错误率
    """
    fpr_list, tpr_list, thresholds = roc_curve(labels, -distances)
    fnr_list = 1 - tpr_list

    # 找到 FPR ≈ FNR 的点
    eer_idx = np.argmin(np.abs(fpr_list - fnr_list))
    eer = (fpr_list[eer_idx] + fnr_list[eer_idx]) / 2
    eer_threshold = -thresholds[eer_idx]

    return float(eer), float(eer_threshold)


def compute_roc_auc(distances, labels):
    """计算 ROC-AUC"""
    fpr, tpr, _ = roc_curve(labels, -distances)
    roc_auc = auc(fpr, tpr)
    return float(roc_auc), fpr, tpr


def evaluate_quantizer(quantizer, embeddings, pairs, pair_labels, quantizer_name, baseline_threshold, metric='euclidean'):
    """
    评估单个量化器的性能（直接在整数域计算）

    Args:
        quantizer: 量化器实例
        embeddings: 原始特征向量
        pairs: 图像对索引
        pair_labels: 图像对标签
        quantizer_name: 量化器名称
        baseline_threshold: 基准阈值（浮点域，使用量化前找到的最优阈值）
        metric: 距离度量，'euclidean' 或 'cosine'

    Returns:
        results: dict containing all evaluation metrics
    """
    print(f"\n{'='*70}")
    print(f"评估: {quantizer_name}")
    print('='*70)

    # 获取缩放因子
    scale_factor = quantizer.scale_factor

    print(f"缩放因子: {scale_factor:,.2f}")
    print(f"距离度量: {metric}")

    # 量化所有特征
    print("[1] 量化特征向量...")
    embeddings_int = np.array([quantizer.quantize(emb) for emb in embeddings])

    # 直接在整数域计算距离（BioZero实际方法）
    print(f"[2] 在整数域计算{metric}距离...")
    distances_int = compute_integer_distances(embeddings_int, pairs, metric=metric)

    # 根据距离度量类型,使用不同的阈值转换方法
    if metric == 'euclidean':
        # 欧式距离: 阈值可以直接缩放
        threshold_int = baseline_threshold * scale_factor
        print(f"[3] 转换阈值到整数域:")
        print(f"    浮点阈值: {baseline_threshold:.6f}")
        print(f"    整数阈值: {threshold_int:,.2f}")
        print(f"    (欧式距离: 线性缩放)")
    else:
        # 余弦距离: 不能直接缩放阈值,需要在整数域重新寻找
        print(f"[3] 在整数域寻找最优阈值:")
        print(f"    (余弦距离不能直接缩放阈值)")
        threshold_int, baseline_metrics = find_optimal_threshold(distances_int, pair_labels)
        print(f"    整数域最优阈值: {threshold_int:,.6f}")
        print(f"    参考浮点阈值: {baseline_threshold:.6f}")

    # 使用整数阈值评估（主要评估指标）
    print(f"[4] 使用整数阈值评估...")
    if metric == 'euclidean':
        baseline_metrics = evaluate_at_threshold(distances_int, pair_labels, threshold_int)

    print(f"  使用整数阈值的性能:")
    print(f"    Precision: {baseline_metrics['precision']:.6f}")
    print(f"    Recall:    {baseline_metrics['recall']:.6f}")
    print(f"    F1-Score:  {baseline_metrics['f1_score']:.6f}")
    print(f"    Accuracy:  {baseline_metrics['accuracy']:.6f}")

    # 计算整数域的最优阈值（仅用于分析对比 - 针对欧式距离）
    if metric == 'euclidean':
        print(f"\n[5] 计算整数域的最优阈值（仅用于分析）...")
        optimal_threshold_int, optimal_metrics_int = find_optimal_threshold(distances_int, pair_labels)
        optimal_threshold_float_equiv = optimal_threshold_int / scale_factor
        print(f"  整数域最优阈值: {optimal_threshold_int:,.2f}")
        print(f"  等价浮点阈值:   {optimal_threshold_float_equiv:.6f}")
        print(f"  最优F1:          {optimal_metrics_int['f1_score']:.6f}")
    else:
        # 余弦距离已经使用了整数域的最优阈值
        optimal_threshold_int = threshold_int
        optimal_metrics_int = baseline_metrics
        print(f"\n[5] 已使用整数域最优阈值")

    # 计算 EER (在整数域)
    print(f"\n[6] 计算 EER (整数域)...")
    eer, eer_threshold_int = compute_eer(distances_int, pair_labels)
    if metric == 'euclidean':
        eer_threshold_float_equiv = eer_threshold_int / scale_factor
        print(f"  EER:             {eer*100:.4f}%")
        print(f"  EER整数阈值:     {eer_threshold_int:,.2f}")
        print(f"  EER等价浮点阈值: {eer_threshold_float_equiv:.6f}")
    else:
        print(f"  EER:             {eer*100:.4f}%")
        print(f"  EER阈值:         {eer_threshold_int:,.6f}")

    # 计算 ROC-AUC (在整数域)
    print(f"[7] 计算 ROC-AUC (整数域)...")
    roc_auc, fpr, tpr = compute_roc_auc(distances_int, pair_labels)
    print(f"  ROC-AUC: {roc_auc:.6f}")

    # 打印主要评估指标（整数域阈值下）
    print("\n" + "="*70)
    print("[主要性能指标] 使用整数域阈值:")
    print("="*70)
    print(f"  参考浮点阈值: {baseline_threshold:.6f}")
    if metric == 'euclidean':
        print(f"  整数阈值:      {threshold_int:,.2f} (缩放转换)")
    else:
        print(f"  整数阈值:      {threshold_int:,.6f} (整数域优化)")
    print(f"  Precision:     {baseline_metrics['precision']:.6f}")
    print(f"  Recall:        {baseline_metrics['recall']:.6f}")
    print(f"  F1-Score:      {baseline_metrics['f1_score']:.6f}")
    print(f"  Accuracy:      {baseline_metrics['accuracy']:.6f}")
    print(f"  TPR:           {baseline_metrics['tpr']:.6f}")
    print(f"  FPR:           {baseline_metrics['fpr']:.6f}")

    # 距离统计（整数域）
    distance_stats_int = {
        'min': float(distances_int.min()),
        'max': float(distances_int.max()),
        'mean': float(distances_int.mean()),
        'std': float(distances_int.std())
    }

    # 距离统计（等价浮点域 - 仅对欧式距离有意义）
    if metric == 'euclidean':
        distance_stats_float_equiv = {
            'min': float(distances_int.min() / scale_factor),
            'max': float(distances_int.max() / scale_factor),
            'mean': float(distances_int.mean() / scale_factor),
            'std': float(distances_int.std() / scale_factor)
        }
    else:
        distance_stats_float_equiv = None

    return {
        'quantizer_name': quantizer_name,
        'scale_factor': float(scale_factor),
        'distance_metric': metric,
        # 主要评估指标（使用整数域阈值）
        'optimal_threshold': baseline_threshold,  # 浮点阈值（用于对比）
        'optimal_threshold_int': float(threshold_int),  # 整数阈值（实际使用）
        'optimal_metrics': baseline_metrics,
        # 整数域的最优阈值（仅用于分析）
        'quantized_optimal_threshold_int': float(optimal_threshold_int),
        'quantized_optimal_threshold_float_equiv': float(optimal_threshold_int / scale_factor) if metric == 'euclidean' else None,
        'quantized_optimal_metrics': optimal_metrics_int,
        # 其他指标
        'eer': eer,
        'eer_threshold_int': float(eer_threshold_int),
        'eer_threshold_float_equiv': float(eer_threshold_int / scale_factor) if metric == 'euclidean' else None,
        'roc_auc': roc_auc,
        'roc_curve': {
            'fpr': fpr.tolist(),
            'tpr': tpr.tolist()
        },
        'distance_stats_int': distance_stats_int,
        'distance_stats_float_equiv': distance_stats_float_equiv
    }


def plot_comparison_results(baseline_results, quantized_results, output_dir):
    """生成对比可视化"""
    print("\n[可视化] 生成对比图表...")

    fig, axes = plt.subplots(2, 2, figsize=(14, 12))

    # 图1: ROC曲线对比
    ax = axes[0, 0]
    ax.plot(baseline_results['roc_curve']['fpr'],
            baseline_results['roc_curve']['tpr'],
            'b-', linewidth=2, label=f"Baseline (AUC={baseline_results['roc_auc']:.4f})")

    for result in quantized_results:
        ax.plot(result['roc_curve']['fpr'],
                result['roc_curve']['tpr'],
                '--', linewidth=1.5, label=f"{result['quantizer_name']} (AUC={result['roc_auc']:.4f})")

    ax.plot([0, 1], [0, 1], 'k--', alpha=0.3)
    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate')
    ax.set_title('ROC Curve Comparison')
    ax.legend(loc='lower right', fontsize=8)
    ax.grid(True, alpha=0.3)

    # 图2: F1-Score 对比
    ax = axes[0, 1]
    names = ['Baseline'] + [r['quantizer_name'] for r in quantized_results]
    f1_scores = [baseline_results['optimal_metrics']['f1_score']] + \
                [r['optimal_metrics']['f1_score'] for r in quantized_results]

    colors = ['blue'] + ['orange', 'green', 'red', 'purple'][:len(quantized_results)]
    bars = ax.bar(range(len(names)), f1_scores, color=colors, alpha=0.7, edgecolor='black')
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel('F1-Score')
    ax.set_title('F1-Score Comparison at Optimal Threshold')
    ax.set_ylim([0, 1.0])

    # 在柱子上标注数值
    for i, bar in enumerate(bars):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.4f}',
                ha='center', va='bottom', fontsize=8)
    ax.grid(True, alpha=0.3, axis='y')

    # 图3: Precision vs Recall
    ax = axes[1, 0]
    ax.scatter(baseline_results['optimal_metrics']['recall'],
               baseline_results['optimal_metrics']['precision'],
               s=200, c='blue', marker='o', edgecolors='black', linewidths=2,
               label='Baseline', zorder=3)

    for result in quantized_results:
        ax.scatter(result['optimal_metrics']['recall'],
                   result['optimal_metrics']['precision'],
                   s=100, marker='^', edgecolors='black', linewidths=1.5,
                   label=result['quantizer_name'], zorder=2)

    ax.set_xlabel('Recall')
    ax.set_ylabel('Precision')
    ax.set_title('Precision-Recall Trade-off')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_xlim([0, 1.05])
    ax.set_ylim([0, 1.05])

    # 图4: EER 对比
    ax = axes[1, 1]
    names = ['Baseline'] + [r['quantizer_name'] for r in quantized_results]
    eer_values = [baseline_results['eer'] * 100] + \
                 [r['eer'] * 100 for r in quantized_results]

    bars = ax.bar(range(len(names)), eer_values, color=colors, alpha=0.7, edgecolor='black')
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel('EER (%)')
    ax.set_title('Equal Error Rate (EER) - Lower is Better')

    # 标注数值
    for i, bar in enumerate(bars):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.4f}%',
                ha='center', va='bottom', fontsize=8)
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    output_file = Path(output_dir) / 'recognition_performance_comparison.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"  ✓ 保存到: {output_file}")

    plt.close()


def main():
    print("="*70)
    print("人脸识别性能评估：量化前后对比")
    print("="*70)
    print(f"实验时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 距离度量选择
    DISTANCE_METRIC = 'cosine'  # 可选: 'euclidean' 或 'cosine'
    print(f"距离度量: {DISTANCE_METRIC}")

    # 数据集大小限制（用于测试，设置为None使用全部数据）
    MAX_IDENTITIES = 200  # 限制身份数量
    print(f"身份数量限制: {MAX_IDENTITIES if MAX_IDENTITIES else '无限制'}")
    print("="*70 + "\n")

    # 设备
    device = torch.device('cpu')
    print(f"设备: {device}\n")

    # 加载模型
    mtcnn, resnet = load_facenet_model(device)

    # 提取特征
    image_dir = "data/lfw/lfw/lfw-deepfunneled"  # LFW数据集路径

    if not Path(image_dir).exists():
        print(f"⚠️  警告: LFW数据集未找到: {image_dir}")
        print("  回退到测试数据集...")
        image_dir = "data/test_images"

    embeddings, labels, image_paths = extract_embeddings_from_dataset(
        mtcnn, resnet, image_dir, device, max_identities=MAX_IDENTITIES
    )

    # 生成图像对
    pairs, pair_labels = generate_pairs_and_labels(embeddings, labels)

    # 计算基准距离（浮点）
    print(f"[基准评估] 浮点特征 (无量化) - 使用{DISTANCE_METRIC}距离")
    print("="*70)
    distances_baseline = compute_distances(embeddings, pairs, metric=DISTANCE_METRIC)

    # 评估基准性能
    optimal_threshold_baseline, optimal_metrics_baseline = find_optimal_threshold(
        distances_baseline, pair_labels
    )
    eer_baseline, eer_threshold_baseline = compute_eer(distances_baseline, pair_labels)
    roc_auc_baseline, fpr_baseline, tpr_baseline = compute_roc_auc(distances_baseline, pair_labels)

    baseline_results = {
        'quantizer_name': 'Baseline_Float32',
        'optimal_threshold': optimal_threshold_baseline,
        'optimal_metrics': optimal_metrics_baseline,
        'eer': eer_baseline,
        'eer_threshold': eer_threshold_baseline,
        'roc_auc': roc_auc_baseline,
        'roc_curve': {
            'fpr': fpr_baseline.tolist(),
            'tpr': tpr_baseline.tolist()
        },
        'distance_stats': {
            'min': float(distances_baseline.min()),
            'max': float(distances_baseline.max()),
            'mean': float(distances_baseline.mean()),
            'std': float(distances_baseline.std())
        }
    }

    print(f"\n最优阈值: {optimal_threshold_baseline:.6f}")
    print(f"F1-Score: {optimal_metrics_baseline['f1_score']:.6f}")
    print(f"Precision: {optimal_metrics_baseline['precision']:.6f}")
    print(f"Recall: {optimal_metrics_baseline['recall']:.6f}")
    print(f"Accuracy: {optimal_metrics_baseline['accuracy']:.6f}")
    print(f"EER: {eer_baseline*100:.4f}%")
    print(f"ROC-AUC: {roc_auc_baseline:.6f}")

    # 测试量化器（使用基准阈值）
    print(f"\n{'='*70}")
    print(f"使用基准阈值 {optimal_threshold_baseline:.6f} 评估量化器")
    print(f"{'='*70}")

    quantizers = [
        (AsymmetricQuantizer(p=67108859), "AsymmetricQuantizer"),
    ]

    quantized_results = []
    for quantizer, name in quantizers:
        result = evaluate_quantizer(quantizer, embeddings, pairs, pair_labels, name, optimal_threshold_baseline, metric=DISTANCE_METRIC)
        quantized_results.append(result)

    # 生成对比报告
    print("\n" + "="*70)
    print("对比总结")
    print("="*70)

    print(f"\n{'量化器':<30} {'F1':<10} {'Precision':<10} {'Recall':<10} {'EER(%)':<10} {'ROC-AUC':<10}")
    print("-"*70)

    # 基准
    print(f"{'Baseline_Float32':<30} "
          f"{baseline_results['optimal_metrics']['f1_score']:<10.6f} "
          f"{baseline_results['optimal_metrics']['precision']:<10.6f} "
          f"{baseline_results['optimal_metrics']['recall']:<10.6f} "
          f"{baseline_results['eer']*100:<10.4f} "
          f"{baseline_results['roc_auc']:<10.6f}")

    # 量化器
    for result in quantized_results:
        print(f"{result['quantizer_name']:<30} "
              f"{result['optimal_metrics']['f1_score']:<10.6f} "
              f"{result['optimal_metrics']['precision']:<10.6f} "
              f"{result['optimal_metrics']['recall']:<10.6f} "
              f"{result['eer']*100:<10.4f} "
              f"{result['roc_auc']:<10.6f}")

    # 计算性能变化
    print("\n[性能变化]")
    for result in quantized_results:
        f1_change = (result['optimal_metrics']['f1_score'] - baseline_results['optimal_metrics']['f1_score']) / baseline_results['optimal_metrics']['f1_score'] * 100
        eer_change = (result['eer'] - baseline_results['eer']) / baseline_results['eer'] * 100
        auc_change = (result['roc_auc'] - baseline_results['roc_auc']) / baseline_results['roc_auc'] * 100

        print(f"\n{result['quantizer_name']}:")
        print(f"  F1变化: {f1_change:+.4f}%")
        print(f"  EER变化: {eer_change:+.4f}%")
        print(f"  AUC变化: {auc_change:+.4f}%")

    # 保存结果
    output_dir = Path("biozero_quantization_experiment/outputs/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results = {
        'experiment': 'Face Recognition Performance Evaluation',
        'distance_metric': DISTANCE_METRIC,
        'timestamp': datetime.now().isoformat(),
        'num_samples': len(embeddings),
        'num_identities': len(set(labels)),
        'num_pairs': len(pairs),
        'num_genuine_pairs': int(sum(pair_labels)),
        'num_impostor_pairs': int(len(pair_labels) - sum(pair_labels)),
        'baseline': baseline_results,
        'quantized': quantized_results
    }

    output_file = output_dir / 'recognition_performance_evaluation.json'
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n结果已保存到: {output_file}")

    # 生成可视化
    plot_comparison_results(baseline_results, quantized_results, output_dir)

    print("\n" + "="*70)
    print("评估完成")
    print("="*70)


if __name__ == "__main__":
    main()