#!/usr/bin/env python3
"""
低位数量化对比实验
评估极低位数（1-7, 9, 13位）对人脸识别性能的影响
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
from pedersen_quantizers import AsymmetricQuantizer, euclidean_distance
from sklearn.metrics import roc_curve, auc, confusion_matrix
import matplotlib.pyplot as plt
from itertools import combinations
from tqdm import tqdm

# 从 evaluate_recognition_performance.py 导入函数
from evaluate_recognition_performance import (
    load_facenet_model,
    compute_distances,
    evaluate_at_threshold,
    find_optimal_threshold,
    compute_eer,
    compute_roc_auc,
    compute_integer_distances,
    cosine_distance
)


# 低位数的质数配置
PRIME_CONFIGS = {
    2: 3,             # 2-bit最大质数: 3 (范围0-2)
    3: 7,             # 3-bit最大质数: 7 (范围0-6)
    4: 13,            # 4-bit接近最大质数: 13
    5: 31,            # 5-bit最大质数: 31
    6: 61,            # 6-bit接近最大质数: 61
    7: 127,           # 7-bit最大质数: 127
    9: 509,           # 9-bit接近质数: 509
    13: 8191,         # 13-bit最大质数 (梅森质数): 8191 = 2^13 - 1
}


def sample_lfw_dataset_fast(lfw_dir, max_identities=50, min_images_per_identity=3):
    """
    快速采样LFW数据集（用于多组实验）

    Args:
        lfw_dir: LFW数据集根目录
        max_identities: 最多采样多少个身份
        min_images_per_identity: 每个身份至少需要多少张图片

    Returns:
        sampled_identities: list of identity names
    """
    print(f"[采样] 从 LFW 数据集快速采样 {max_identities} 个身份...")

    lfw_path = Path(lfw_dir)
    identity_stats = {}

    for person_dir in lfw_path.iterdir():
        if person_dir.is_dir() and not person_dir.name.startswith('.'):
            images = list(person_dir.glob("*.jpg"))
            if len(images) >= min_images_per_identity:
                identity_stats[person_dir.name] = len(images)

    # 按图片数排序，选择图片最多的身份
    sorted_identities = sorted(identity_stats.items(), key=lambda x: -x[1])
    sampled = sorted_identities[:max_identities]

    print(f"  ✓ 采样 {len(sampled)} 个身份")

    return [name for name, _ in sampled]


def extract_embeddings_from_sampled_lfw(mtcnn, resnet, lfw_dir, sampled_identities, device):
    """
    从采样的身份中提取特征向量
    """
    print(f"[特征提取] 从 {len(sampled_identities)} 个身份中提取...")

    embeddings = []
    labels = []
    image_paths = []

    lfw_path = Path(lfw_dir)

    for identity in tqdm(sampled_identities, desc="提取特征"):
        person_dir = lfw_path / identity

        if not person_dir.exists():
            continue

        for img_file in sorted(person_dir.glob("*.jpg")):
            try:
                img = Image.open(img_file)
                img_cropped = mtcnn(img)

                if img_cropped is not None:
                    with torch.no_grad():
                        embedding = resnet(img_cropped.unsqueeze(0)).cpu().numpy()[0]
                        embeddings.append(embedding)
                        labels.append(identity)
                        image_paths.append(str(img_file))
            except Exception as e:
                pass  # 静默跳过错误

    embeddings = np.array(embeddings)
    print(f"  ✓ 提取完成: {len(embeddings)} 个样本, {len(set(labels))} 个身份")

    return embeddings, labels, image_paths


def generate_pairs_and_labels(embeddings, labels):
    """生成所有可能的图像对及其真实标签"""
    print("[对生成] 生成图像对...")

    pairs = []
    pair_labels = []

    n = len(embeddings)

    for i, j in combinations(range(n), 2):
        pairs.append((i, j))
        pair_labels.append(1 if labels[i] == labels[j] else 0)

    genuine_pairs = sum(pair_labels)
    impostor_pairs = len(pair_labels) - genuine_pairs

    print(f"  ✓ 总对数: {len(pairs):,} (正样本: {genuine_pairs:,}, 负样本: {impostor_pairs:,})")

    return pairs, np.array(pair_labels)


def evaluate_quantizer_with_prime(prime_p, bits, embeddings, pairs, pair_labels, baseline_threshold, metric='euclidean'):
    """
    评估单个质数配置的量化性能

    Args:
        prime_p: 质数
        bits: 位数标识
        embeddings: 原始特征向量
        pairs: 图像对索引
        pair_labels: 图像对标签
        baseline_threshold: 基准阈值（浮点域）
        metric: 距离度量，'euclidean' 或 'cosine'

    Returns:
        results: dict containing all evaluation metrics
    """
    quantizer_name = f"AsymmetricQuantizer_{bits}bit"

    print(f"\n{'='*70}")
    print(f"[{bits}-bit] 质数 p = {prime_p:,}, 距离度量 = {metric}")
    print('='*70)

    # 初始化量化器
    quantizer = AsymmetricQuantizer(p=prime_p)
    scale_factor = quantizer.scale_factor

    # 量化所有特征
    print(f"  [1/5] 量化特征向量...")
    embeddings_int = np.array([quantizer.quantize(emb) for emb in embeddings])

    # 在整数域计算距离
    print(f"  [2/5] 计算整数域{metric}距离...")
    distances_int = compute_integer_distances(embeddings_int, pairs, metric=metric)

    # 根据距离度量类型选择阈值转换方法
    if metric == 'euclidean':
        # 欧式距离: 阈值可以直接缩放
        threshold_int = baseline_threshold * scale_factor
    else:
        # 余弦距离: 需要在整数域重新寻找最优阈值
        print(f"  [3/5] 在整数域寻找最优阈值（余弦距离）...")
        threshold_int, metrics = find_optimal_threshold(distances_int, pair_labels)
        print(f"       整数域最优阈值: {threshold_int:.6f}")

        # 直接使用找到的指标
        eer, eer_threshold_int = compute_eer(distances_int, pair_labels)
        roc_auc, fpr, tpr = compute_roc_auc(distances_int, pair_labels)

        # 计算 FAR 和 FRR（在使用的阈值处）
        predictions = (distances_int < threshold_int).astype(int)

        # 计算混淆矩阵
        tn = np.sum((predictions == 0) & (pair_labels == 0))  # True Negative (正确拒绝)
        fp = np.sum((predictions == 1) & (pair_labels == 0))  # False Positive (错误接受)
        fn = np.sum((predictions == 0) & (pair_labels == 1))  # False Negative (错误拒绝)
        tp = np.sum((predictions == 1) & (pair_labels == 1))  # True Positive (正确接受)

        # FAR = FP / (FP + TN) - 错误接受率
        far = fp / (fp + tn) if (fp + tn) > 0 else 0.0

        # FRR = FN / (FN + TP) - 错误拒绝率
        frr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

        # 打印关键指标
        print(f"\n  性能指标:")
        print(f"    F1-Score:  {metrics['f1_score']:.6f}")
        print(f"    Precision: {metrics['precision']:.6f}")
        print(f"    Recall:    {metrics['recall']:.6f}")
        print(f"    Accuracy:  {metrics['accuracy']:.6f}")
        print(f"    EER:       {eer*100:.4f}%")
        print(f"    FAR:       {far*100:.4f}%")
        print(f"    FRR:       {frr*100:.4f}%")
        print(f"    ROC-AUC:   {roc_auc:.6f}")

        return {
            'quantizer_name': quantizer_name,
            'bits': bits,
            'prime': prime_p,
            'scale_factor': float(scale_factor),
            'distance_metric': metric,
            'threshold_float': baseline_threshold,
            'threshold_int': float(threshold_int),
            'optimal_metrics': metrics,
            'eer': eer,
            'far': far,
            'frr': frr,
            'roc_auc': roc_auc,
            'roc_curve': {
                'fpr': fpr.tolist(),
                'tpr': tpr.tolist()
            }
        }

    # 欧式距离的处理逻辑
    # 转换阈值到整数域
    threshold_int = baseline_threshold * scale_factor

    # 使用整数阈值评估
    print(f"  [3/5] 评估性能...")
    metrics = evaluate_at_threshold(distances_int, pair_labels, threshold_int)

    # 计算 EER
    print(f"  [4/5] 计算 EER...")
    eer, eer_threshold_int = compute_eer(distances_int, pair_labels)

    # 计算 ROC-AUC
    print(f"  [5/5] 计算 ROC-AUC...")
    roc_auc, fpr, tpr = compute_roc_auc(distances_int, pair_labels)

    # 计算 FAR 和 FRR（在使用的阈值处）
    predictions = (distances_int < threshold_int).astype(int)

    # 计算混淆矩阵
    tn = np.sum((predictions == 0) & (pair_labels == 0))  # True Negative (正确拒绝)
    fp = np.sum((predictions == 1) & (pair_labels == 0))  # False Positive (错误接受)
    fn = np.sum((predictions == 0) & (pair_labels == 1))  # False Negative (错误拒绝)
    tp = np.sum((predictions == 1) & (pair_labels == 1))  # True Positive (正确接受)

    # FAR = FP / (FP + TN) - 错误接受率
    far = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    # FRR = FN / (FN + TP) - 错误拒绝率
    frr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

    # 打印关键指标
    print(f"\n  性能指标:")
    print(f"    F1-Score:  {metrics['f1_score']:.6f}")
    print(f"    Precision: {metrics['precision']:.6f}")
    print(f"    Recall:    {metrics['recall']:.6f}")
    print(f"    Accuracy:  {metrics['accuracy']:.6f}")
    print(f"    EER:       {eer*100:.4f}%")
    print(f"    FAR:       {far*100:.4f}%")
    print(f"    FRR:       {frr*100:.4f}%")
    print(f"    ROC-AUC:   {roc_auc:.6f}")

    return {
        'quantizer_name': quantizer_name,
        'bits': bits,
        'prime': prime_p,
        'scale_factor': float(scale_factor),
        'distance_metric': metric,
        'threshold_float': baseline_threshold,
        'threshold_int': float(threshold_int),
        'optimal_metrics': metrics,
        'eer': eer,
        'far': far,
        'frr': frr,
        'roc_auc': roc_auc,
        'roc_curve': {
            'fpr': fpr.tolist(),
            'tpr': tpr.tolist()
        }
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description='低位数量化对比实验')
    parser.add_argument('--distance', type=str, choices=['euclidean', 'cosine', 'both'],
                       default='both', help='距离度量方式: euclidean, cosine, 或 both')
    args = parser.parse_args()

    print("="*70)
    print("低位数量化对比实验 (2-7, 9, 13 位)")
    print("="*70)
    print(f"实验时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"距离度量: {args.distance}")
    print("="*70 + "\n")

    # 设备
    device = torch.device('cpu')
    print(f"设备: {device}\n")

    # LFW 数据集路径
    lfw_dir = "data/lfw/lfw/lfw-deepfunneled"

    if not Path(lfw_dir).exists():
        print(f"✗ 错误: LFW 数据集未找到: {lfw_dir}")
        return

    # 采样身份（减少样本以加快多组实验速度）
    sampled_identities = sample_lfw_dataset_fast(
        lfw_dir,
        max_identities=50,  # 减少到50个身份以加快速度
        min_images_per_identity=3
    )

    # 加载模型
    mtcnn, resnet = load_facenet_model(device)

    # 提取特征
    embeddings, labels, image_paths = extract_embeddings_from_sampled_lfw(
        mtcnn, resnet, lfw_dir, sampled_identities, device
    )

    # 生成图像对
    pairs, pair_labels = generate_pairs_and_labels(embeddings, labels)

    # 确定要测试的距离度量
    if args.distance == 'both':
        distance_metrics = ['euclidean', 'cosine']
    else:
        distance_metrics = [args.distance]

    all_results = {}

    # 对每种距离度量进行评估
    for distance_metric in distance_metrics:
        print(f"\n{'='*70}")
        print(f"测试距离度量: {distance_metric.upper()}")
        print(f"{'='*70}")

        # 计算基准距离（浮点）
        print(f"\n[基准评估] 浮点特征 (无量化) - 使用{distance_metric}距离")
        print("="*70)
        distances_baseline = compute_distances(embeddings, pairs, metric=distance_metric)

        optimal_threshold_baseline, optimal_metrics_baseline = find_optimal_threshold(
            distances_baseline, pair_labels
        )
        eer_baseline, eer_threshold_baseline = compute_eer(distances_baseline, pair_labels)
        roc_auc_baseline, fpr_baseline, tpr_baseline = compute_roc_auc(distances_baseline, pair_labels)

        # 计算基准 FAR 和 FRR
        predictions_baseline = (distances_baseline < optimal_threshold_baseline).astype(int)
        tn = np.sum((predictions_baseline == 0) & (pair_labels == 0))
        fp = np.sum((predictions_baseline == 1) & (pair_labels == 0))
        fn = np.sum((predictions_baseline == 0) & (pair_labels == 1))
        tp = np.sum((predictions_baseline == 1) & (pair_labels == 1))
        far_baseline = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        frr_baseline = fn / (fn + tp) if (fn + tp) > 0 else 0.0

        baseline_results = {
            'quantizer_name': 'Baseline_Float32',
            'distance_metric': distance_metric,
            'optimal_threshold': optimal_threshold_baseline,
            'optimal_metrics': optimal_metrics_baseline,
            'eer': eer_baseline,
            'eer_threshold': eer_threshold_baseline,
            'far': far_baseline,
            'frr': frr_baseline,
            'roc_auc': roc_auc_baseline,
            'roc_curve': {
                'fpr': fpr_baseline.tolist(),
                'tpr': tpr_baseline.tolist()
            }
        }

        print(f"\n最优阈值: {optimal_threshold_baseline:.6f}")
        print(f"F1-Score: {optimal_metrics_baseline['f1_score']:.6f}")
        print(f"Accuracy: {optimal_metrics_baseline['accuracy']:.6f}")
        print(f"EER: {eer_baseline*100:.4f}%")
        print(f"FAR: {far_baseline*100:.4f}%")
        print(f"FRR: {frr_baseline*100:.4f}%")
        print(f"ROC-AUC: {roc_auc_baseline:.6f}")

        # 测试不同位数的量化器
        print(f"\n{'='*70}")
        print(f"低位数量化对比实验 - {distance_metric.upper()}")
        print(f"{'='*70}")

        # 选择要测试的位数 (2-7, 9, 13)
        # 对于余弦距离，跳过2-3位以避免数值不稳定性
        if distance_metric == 'cosine':
            test_bits = [4, 5, 6, 7, 9, 13]  # Skip 2-3 bit for cosine
        else:
            test_bits = [2, 3, 4, 5, 6, 7, 9, 13]  # Test all bits for euclidean

        quantized_results = []
        for bits in test_bits:
            prime = PRIME_CONFIGS[bits]
            result = evaluate_quantizer_with_prime(
                prime, bits, embeddings, pairs, pair_labels, optimal_threshold_baseline, metric=distance_metric
            )
            quantized_results.append(result)

        # 生成对比报告
        print("\n" + "="*70)
        print(f"对比总结 - {distance_metric.upper()}")
        print("="*70)

        print(f"\n{'配置':<20} {'F1':<12} {'Precision':<12} {'Recall':<12} {'Accuracy':<12} {'EER(%)':<10} {'ROC-AUC':<10}")
        print("-"*90)

        # 基准
        print(f"{'Baseline (Float)':<20} "
              f"{baseline_results['optimal_metrics']['f1_score']:<12.6f} "
              f"{baseline_results['optimal_metrics']['precision']:<12.6f} "
              f"{baseline_results['optimal_metrics']['recall']:<12.6f} "
              f"{baseline_results['optimal_metrics']['accuracy']:<12.6f} "
              f"{baseline_results['eer']*100:<10.4f} "
              f"{baseline_results['roc_auc']:<10.6f}")

        # 量化结果
        for result in quantized_results:
            config_name = f"{result['bits']}-bit"
            print(f"{config_name:<20} "
                  f"{result['optimal_metrics']['f1_score']:<12.6f} "
                  f"{result['optimal_metrics']['precision']:<12.6f} "
                  f"{result['optimal_metrics']['recall']:<12.6f} "
                  f"{result['optimal_metrics']['accuracy']:<12.6f} "
                  f"{result['eer']*100:<10.4f} "
                  f"{result['roc_auc']:<10.6f}")

        # 计算性能变化
        print("\n[性能变化]")
        print(f"{'配置':<20} {'F1变化':<15} {'Accuracy变化':<15} {'EER变化':<15} {'AUC变化':<15}")
        print("-"*80)

        for result in quantized_results:
            f1_change = (result['optimal_metrics']['f1_score'] - baseline_results['optimal_metrics']['f1_score']) / baseline_results['optimal_metrics']['f1_score'] * 100
            acc_change = (result['optimal_metrics']['accuracy'] - baseline_results['optimal_metrics']['accuracy']) / baseline_results['optimal_metrics']['accuracy'] * 100
            eer_change = (result['eer'] - baseline_results['eer']) / baseline_results['eer'] * 100
            auc_change = (result['roc_auc'] - baseline_results['roc_auc']) / baseline_results['roc_auc'] * 100

            config_name = f"{result['bits']}-bit"
            print(f"{config_name:<20} "
                  f"{f1_change:>+14.4f}% "
                  f"{acc_change:>+14.4f}% "
                  f"{eer_change:>+14.4f}% "
                  f"{auc_change:>+14.4f}%")

        # 保存结果
        output_dir = Path("biozero_quantization_experiment/outputs/results")
        output_dir.mkdir(parents=True, exist_ok=True)

        results_data = {
            'experiment': 'Low-Bit Quantization Comparison - FaceNet (InceptionResnetV1)',
            'model': 'InceptionResnetV1',
            'embedding_dimension': 512,
            'distance_metric': distance_metric,
            'timestamp': datetime.now().isoformat(),
            'num_samples': len(embeddings),
            'num_identities': len(set(labels)),
            'num_pairs': len(pairs),
            'num_genuine_pairs': int(sum(pair_labels)),
            'num_impostor_pairs': int(len(pair_labels) - sum(pair_labels)),
            'baseline': baseline_results,
            'quantized': quantized_results
        }

        all_results[distance_metric] = results_data

        output_file = output_dir / f'facenet512d_low_bit_{distance_metric}_comparison.json'
        with open(output_file, 'w') as f:
            json.dump(results_data, f, indent=2)

        print(f"\n结果已保存到: {output_file}")

        # 生成可视化（每个距离度量单独生成）
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))

        # 提取数据
        bits_list = [r['bits'] for r in quantized_results]
        f1_scores = [r['optimal_metrics']['f1_score'] for r in quantized_results]
        precisions = [r['optimal_metrics']['precision'] for r in quantized_results]
        recalls = [r['optimal_metrics']['recall'] for r in quantized_results]
        accuracies = [r['optimal_metrics']['accuracy'] for r in quantized_results]
        eers = [r['eer'] * 100 for r in quantized_results]
        aucs = [r['roc_auc'] for r in quantized_results]

        baseline_f1 = baseline_results['optimal_metrics']['f1_score']
        baseline_acc = baseline_results['optimal_metrics']['accuracy']
        baseline_eer = baseline_results['eer'] * 100
        baseline_auc = baseline_results['roc_auc']

        # 图1: F1-Score vs 位数
        ax = axes[0, 0]
        ax.plot(bits_list, f1_scores, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_f1, color='r', linestyle='--', linewidth=2, label='Baseline (Float)')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('F1-Score', fontsize=12)
        ax.set_title(f'F1-Score vs Quantization Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        if len(f1_scores) > 0 and max(f1_scores) > 0:
            ax.set_ylim([max(0, min(f1_scores) - 0.05), 1.0])

        # 图2: Accuracy vs 位数
        ax = axes[0, 1]
        ax.plot(bits_list, accuracies, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_acc, color='r', linestyle='--', linewidth=2, label='Baseline (Float)')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('Accuracy', fontsize=12)
        ax.set_title(f'Accuracy vs Quantization Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        if len(accuracies) > 0 and max(accuracies) > 0:
            ax.set_ylim([max(0, min(accuracies) - 0.01), 1.0])

        # 图3: EER vs 位数 (越低越好)
        ax = axes[0, 2]
        ax.plot(bits_list, eers, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_eer, color='r', linestyle='--', linewidth=2, label='Baseline (Float)')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('EER (%)', fontsize=12)
        ax.set_title(f'Equal Error Rate vs Quantization Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # 图4: ROC-AUC vs 位数
        ax = axes[1, 0]
        ax.plot(bits_list, aucs, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_auc, color='r', linestyle='--', linewidth=2, label='Baseline (Float)')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('ROC-AUC', fontsize=12)
        ax.set_title(f'ROC-AUC vs Quantization Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        if len(aucs) > 0 and max(aucs) > 0:
            ax.set_ylim([max(0, min(aucs) - 0.05), 1.0])

        # 图5: Precision & Recall vs 位数
        ax = axes[1, 1]
        ax.plot(bits_list, precisions, 'o-', linewidth=2, markersize=8, label='Precision')
        ax.plot(bits_list, recalls, 's-', linewidth=2, markersize=8, label='Recall')
        ax.axhline(y=baseline_results['optimal_metrics']['precision'],
                   color='r', linestyle='--', linewidth=1, alpha=0.5)
        ax.axhline(y=baseline_results['optimal_metrics']['recall'],
                   color='b', linestyle='--', linewidth=1, alpha=0.5)
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('Score', fontsize=12)
        ax.set_title(f'Precision & Recall vs Quantization Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # 图6: 性能下降百分比
        ax = axes[1, 2]
        f1_drops = [(baseline_f1 - f1) / baseline_f1 * 100 if baseline_f1 > 0 else 0 for f1 in f1_scores]
        acc_drops = [(baseline_acc - acc) / baseline_acc * 100 if baseline_acc > 0 else 0 for acc in accuracies]

        x = np.arange(len(bits_list))
        width = 0.35

        bars1 = ax.bar(x - width/2, f1_drops, width, label='F1 Drop', alpha=0.8)
        bars2 = ax.bar(x + width/2, acc_drops, width, label='Accuracy Drop', alpha=0.8)

        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('Performance Drop (%)', fontsize=12)
        ax.set_title(f'Performance Drop vs Quantization Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(bits_list)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        ax.axhline(y=0, color='black', linewidth=0.5)

        plt.tight_layout()
        plot_file = output_dir / f'facenet512d_low_bit_{distance_metric}_comparison.png'
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"  ✓ 可视化保存到: {plot_file}")
        plt.close()

    # 保存综合报告
    print("\n" + "="*70)
    print("所有距离度量评估完成")
    print("="*70)

    # 生成文本报告
    for distance_metric, results_data in all_results.items():
        report_file = output_dir / f'facenet512d_low_bit_{distance_metric}_report.txt'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*70 + "\n")
            f.write(f"低位数量化对比报告 - {distance_metric.upper()} 距离\n")
            f.write("="*70 + "\n")
            f.write(f"模型: {results_data['model']}\n")
            f.write(f"嵌入维度: {results_data['embedding_dimension']}d\n")
            f.write(f"实验时间: {results_data['timestamp']}\n")
            f.write(f"距离度量: {distance_metric}\n")
            f.write(f"样本数量: {results_data['num_samples']}\n")
            f.write(f"身份数量: {results_data['num_identities']}\n")
            f.write(f"图像对数量: {results_data['num_pairs']}\n")
            f.write(f"正样本对: {results_data['num_genuine_pairs']}\n")
            f.write(f"负样本对: {results_data['num_impostor_pairs']}\n\n")

            baseline = results_data['baseline']
            f.write("[基准性能]\n")
            f.write(f"  准确率: {baseline['optimal_metrics']['accuracy']:.6f}\n")
            f.write(f"  F1分数: {baseline['optimal_metrics']['f1_score']:.6f}\n")
            f.write(f"  精确率: {baseline['optimal_metrics']['precision']:.6f}\n")
            f.write(f"  召回率: {baseline['optimal_metrics']['recall']:.6f}\n")
            f.write(f"  ROC-AUC: {baseline['roc_auc']:.6f}\n")
            f.write(f"  EER: {baseline['eer']*100:.4f}%\n")
            if 'far' in baseline:
                f.write(f"  FAR: {baseline['far']*100:.4f}%\n")
                f.write(f"  FRR: {baseline['frr']*100:.4f}%\n")
            f.write(f"  最优阈值: {baseline['optimal_threshold']:.6f}\n\n")

            f.write("[量化性能对比]\n")
            f.write(f"{'位数':<10} {'F1分数':<12} {'准确率':<12} {'精确率':<12} {'召回率':<12} {'EER(%)':<10} {'FAR(%)':<10} {'FRR(%)':<10} {'ROC-AUC':<10}\n")
            f.write("-"*110 + "\n")

            for result in results_data['quantized']:
                f.write(f"{result['bits']:<10} "
                       f"{result['optimal_metrics']['f1_score']:<12.6f} "
                       f"{result['optimal_metrics']['accuracy']:<12.6f} "
                       f"{result['optimal_metrics']['precision']:<12.6f} "
                       f"{result['optimal_metrics']['recall']:<12.6f} "
                       f"{result['eer']*100:<10.4f} "
                       f"{result.get('far', 0)*100:<10.4f} "
                       f"{result.get('frr', 0)*100:<10.4f} "
                       f"{result['roc_auc']:<10.6f}\n")

            f.write("\n[性能变化]\n")
            f.write(f"{'位数':<10} {'F1变化':<15} {'准确率变化':<15} {'EER变化':<15} {'AUC变化':<15}\n")
            f.write("-"*70 + "\n")

            for result in results_data['quantized']:
                f1_change = (result['optimal_metrics']['f1_score'] - baseline['optimal_metrics']['f1_score']) / baseline['optimal_metrics']['f1_score'] * 100 if baseline['optimal_metrics']['f1_score'] > 0 else 0
                acc_change = (result['optimal_metrics']['accuracy'] - baseline['optimal_metrics']['accuracy']) / baseline['optimal_metrics']['accuracy'] * 100 if baseline['optimal_metrics']['accuracy'] > 0 else 0
                eer_change = (result['eer'] - baseline['eer']) / baseline['eer'] * 100 if baseline['eer'] > 0 else 0
                auc_change = (result['roc_auc'] - baseline['roc_auc']) / baseline['roc_auc'] * 100 if baseline['roc_auc'] > 0 else 0

                f.write(f"{result['bits']:<10} "
                       f"{f1_change:>+14.4f}% "
                       f"{acc_change:>+14.4f}% "
                       f"{eer_change:>+14.4f}% "
                       f"{auc_change:>+14.4f}%\n")

        print(f"{distance_metric.upper()} 报告已保存到: {report_file}")

    print("\n" + "="*70)
    print("评估完成")
    print("="*70)


if __name__ == "__main__":
    main()
