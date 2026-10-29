#!/usr/bin/env python3
"""
FaceNet-MobileNet 低位数量化评估

测试极低位数（2-7, 9, 13位）对人脸识别性能的影响
使用LFW官方评估协议
"""

import sys
sys.path.append('biozero_quantization_experiment/scripts')
sys.path.append('/Volumes/TSU302/BioZero/workplace/facenetMRL2_存档')

import torch
import numpy as np
from PIL import Image
from pathlib import Path
import json
from datetime import datetime
from pedersen_quantizers import AsymmetricQuantizer
from sklearn.model_selection import KFold
from tqdm import tqdm
import os
import matplotlib.pyplot as plt

# 从facenetMRL2_存档导入
from nets.facenet import Facenet as FacenetMobileNet
from utils.utils import resize_image, preprocess_input

# 从evaluate_recognition_performance导入评估函数
from evaluate_recognition_performance import (
    compute_eer,
    compute_roc_auc,
    find_optimal_threshold,
    evaluate_at_threshold
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


def load_mobilenet_model(model_path, embedding_size=128, device='cpu'):
    """加载FaceNet-MobileNet模型"""
    print(f"[模型加载] FaceNet-MobileNet...")
    print(f"  模型路径: {model_path}")
    print(f"  嵌入维度: {embedding_size}")
    print(f"  设备: {device}")

    model = FacenetMobileNet(
        backbone="mobilenet",
        embedding_size=embedding_size,
        mode="predict",
        pretrained=False
    )

    state_dict = torch.load(model_path, map_location=device)
    model.load_state_dict(state_dict, strict=False)
    model.eval()
    model.to(device)

    print("✓ 模型加载完成\n")
    return model


def read_lfw_pairs(pairs_filename):
    """读取LFW pairs文件"""
    pairs = []
    with open(pairs_filename, 'r') as f:
        for line in f.readlines()[1:]:  # 跳过第一行
            pair = line.strip().split()
            pairs.append(pair)
    return np.array(pairs, dtype=object)


def get_lfw_paths(lfw_dir, pairs_path, file_ext="jpg", max_samples=None):
    """
    根据pairs.txt获取图像路径和标签

    Returns:
        path_list: [(path0, path1, issame), ...]
        issame_list: [True/False, ...]
    """
    pairs = read_lfw_pairs(pairs_path)

    nrof_skipped_pairs = 0
    path_list = []
    issame_list = []

    for i, pair in enumerate(pairs):
        if max_samples and i >= max_samples:
            break

        if len(pair) == 3:
            # 同一个人的两张图片
            path0 = os.path.join(lfw_dir, pair[0], f"{pair[0]}_{int(pair[1]):04d}.{file_ext}")
            path1 = os.path.join(lfw_dir, pair[0], f"{pair[0]}_{int(pair[2]):04d}.{file_ext}")
            issame = True
        elif len(pair) == 4:
            # 不同人的两张图片
            path0 = os.path.join(lfw_dir, pair[0], f"{pair[0]}_{int(pair[1]):04d}.{file_ext}")
            path1 = os.path.join(lfw_dir, pair[2], f"{pair[2]}_{int(pair[3]):04d}.{file_ext}")
            issame = False
        else:
            continue

        if os.path.exists(path0) and os.path.exists(path1):
            path_list.append((path0, path1, issame))
            issame_list.append(issame)
        else:
            nrof_skipped_pairs += 1

    if nrof_skipped_pairs > 0:
        print(f"  跳过 {nrof_skipped_pairs} 对图片（文件不存在）")

    return path_list, issame_list


def extract_embeddings_mobilenet(model, image_path, input_shape=(160, 160), device='cpu'):
    """提取单张图片的特征向量"""
    try:
        image = Image.open(image_path).convert('RGB')
        image = resize_image(image, input_shape, letterbox_image=True)
        photo = np.array(image, dtype=np.float32)
        photo = np.transpose(preprocess_input(photo), (2, 0, 1))

        with torch.no_grad():
            photo_tensor = torch.from_numpy(photo).unsqueeze(0).to(device)
            embedding = model(photo_tensor).cpu().numpy()[0]

        return embedding
    except Exception as e:
        print(f"  提取失败: {image_path}, 错误: {e}")
        return None


def compute_distances_from_pairs(embeddings1, embeddings2, metric='euclidean'):
    """计算两组特征向量之间的距离"""
    if metric == 'euclidean':
        diff = embeddings1 - embeddings2
        distances = np.sqrt(np.sum(diff ** 2, axis=1))
    elif metric == 'cosine':
        # 余弦距离 = 1 - 余弦相似度
        dot_product = np.sum(embeddings1 * embeddings2, axis=1)
        norm1 = np.linalg.norm(embeddings1, axis=1)
        norm2 = np.linalg.norm(embeddings2, axis=1)
        cosine_similarity = dot_product / (norm1 * norm2 + 1e-10)
        distances = 1.0 - cosine_similarity
    else:
        raise ValueError(f"Unknown metric: {metric}")

    return distances


def evaluate_quantizer_low_bit(prime_p, bits, embeddings1, embeddings2, labels,
                                baseline_threshold, metric='euclidean'):
    """
    评估低位数量化性能

    Args:
        prime_p: 质数
        bits: 位数
        embeddings1: 第一组特征向量
        embeddings2: 第二组特征向量
        labels: 真实标签
        baseline_threshold: 基准阈值
        metric: 距离度量
    """
    quantizer_name = f"AsymmetricQuantizer_{bits}bit"

    print(f"\n{'='*70}")
    print(f"[{bits}-bit] 质数 p = {prime_p:,}, 距离度量 = {metric}")
    print('='*70)

    # 初始化量化器
    quantizer = AsymmetricQuantizer(p=prime_p)
    scale_factor = quantizer.scale_factor

    # 量化特征向量
    print(f"  [1/5] 量化特征向量...")
    emb1_int = np.array([quantizer.quantize(emb) for emb in embeddings1])
    emb2_int = np.array([quantizer.quantize(emb) for emb in embeddings2])

    # 计算整数域距离
    print(f"  [2/5] 计算整数域{metric}距离...")
    distances_int = compute_distances_from_pairs(emb1_int, emb2_int, metric=metric)

    # 根据度量选择阈值处理方式
    if metric == 'euclidean':
        # 欧式距离: 直接缩放阈值
        threshold_int = baseline_threshold * scale_factor
    else:
        # 余弦距离: 重新寻找最优阈值
        print(f"  [3/5] 在整数域寻找最优阈值（余弦距离）...")
        threshold_int, metrics = find_optimal_threshold(distances_int, labels)
        print(f"       整数域最优阈值: {threshold_int:.6f}")

        # 计算其他指标
        eer, eer_threshold_int = compute_eer(distances_int, labels)
        roc_auc, fpr, tpr = compute_roc_auc(distances_int, labels)

        # 计算 FAR 和 FRR
        predictions = (distances_int < threshold_int).astype(int)
        tn = np.sum((predictions == 0) & (labels == 0))
        fp = np.sum((predictions == 1) & (labels == 0))
        fn = np.sum((predictions == 0) & (labels == 1))
        tp = np.sum((predictions == 1) & (labels == 1))

        far = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        frr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

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

    # 欧式距离的处理
    threshold_int = baseline_threshold * scale_factor

    print(f"  [3/5] 评估性能...")
    metrics = evaluate_at_threshold(distances_int, labels, threshold_int)

    print(f"  [4/5] 计算 EER...")
    eer, eer_threshold_int = compute_eer(distances_int, labels)

    print(f"  [5/5] 计算 ROC-AUC...")
    roc_auc, fpr, tpr = compute_roc_auc(distances_int, labels)

    # 计算 FAR 和 FRR
    predictions = (distances_int < threshold_int).astype(int)
    tn = np.sum((predictions == 0) & (labels == 0))
    fp = np.sum((predictions == 1) & (labels == 0))
    fn = np.sum((predictions == 0) & (labels == 1))
    tp = np.sum((predictions == 1) & (labels == 1))

    far = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    frr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

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
    parser = argparse.ArgumentParser(description='MobileNet低位数量化实验')
    parser.add_argument('--distance', type=str, choices=['euclidean', 'cosine', 'both'],
                       default='both', help='距离度量方式')
    parser.add_argument('--max-samples', type=int, default=None,
                       help='最大样本数（用于快速测试）')
    args = parser.parse_args()

    print("="*70)
    print("FaceNet-MobileNet 低位数量化实验 (2-7, 9, 13 位)")
    print("="*70)
    print(f"实验时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"距离度量: {args.distance}")
    if args.max_samples:
        print(f"最大样本数: {args.max_samples}")
    print("="*70 + "\n")

    # 设备
    device = torch.device('cpu')
    print(f"设备: {device}\n")

    # 路径配置
    model_path = "biozero_quantization_experiment/models/facenet_mobilenet.pth"
    lfw_dir = "/Volumes/TSU302/BioZero/workplace/facenetMRL2_存档/lfw"
    pairs_path = "/Volumes/TSU302/BioZero/workplace/facenetMRL2_存档/model_data/lfw_pair.txt"

    if not Path(model_path).exists():
        print(f"✗ 错误: 模型文件未找到: {model_path}")
        return
    if not Path(lfw_dir).exists():
        print(f"✗ 错误: LFW数据集未找到: {lfw_dir}")
        return
    if not Path(pairs_path).exists():
        print(f"✗ 错误: pairs.txt未找到: {pairs_path}")
        return

    # 加载模型
    model = load_mobilenet_model(model_path, embedding_size=128, device=device)

    # 读取LFW pairs
    print("[数据加载] 读取LFW官方评估协议...")
    path_list, issame_list = get_lfw_paths(lfw_dir, pairs_path, max_samples=args.max_samples)
    print(f"  ✓ 图像对数量: {len(path_list)}")
    print(f"  ✓ 正样本对: {sum(issame_list)}")
    print(f"  ✓ 负样本对: {len(issame_list) - sum(issame_list)}\n")

    # 提取特征向量
    print("[特征提取] 提取特征向量...")
    embeddings1 = []
    embeddings2 = []
    valid_labels = []

    for (path0, path1, issame) in tqdm(path_list, desc="提取特征"):
        emb0 = extract_embeddings_mobilenet(model, path0, device=device)
        emb1 = extract_embeddings_mobilenet(model, path1, device=device)

        if emb0 is not None and emb1 is not None:
            embeddings1.append(emb0)
            embeddings2.append(emb1)
            valid_labels.append(1 if issame else 0)

    embeddings1 = np.array(embeddings1)
    embeddings2 = np.array(embeddings2)
    labels = np.array(valid_labels)

    print(f"  ✓ 有效样本对: {len(labels)}\n")

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

        # 计算基准距离
        print(f"\n[基准评估] 浮点特征 (无量化) - 使用{distance_metric}距离")
        print("="*70)
        distances_baseline = compute_distances_from_pairs(embeddings1, embeddings2, metric=distance_metric)

        optimal_threshold_baseline, optimal_metrics_baseline = find_optimal_threshold(
            distances_baseline, labels
        )
        eer_baseline, eer_threshold_baseline = compute_eer(distances_baseline, labels)
        roc_auc_baseline, fpr_baseline, tpr_baseline = compute_roc_auc(distances_baseline, labels)

        # 计算基准 FAR 和 FRR
        predictions_baseline = (distances_baseline < optimal_threshold_baseline).astype(int)
        tn = np.sum((predictions_baseline == 0) & (labels == 0))
        fp = np.sum((predictions_baseline == 1) & (labels == 0))
        fn = np.sum((predictions_baseline == 0) & (labels == 1))
        tp = np.sum((predictions_baseline == 1) & (labels == 1))
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

        # 测试低位数量化
        print(f"\n{'='*70}")
        print(f"低位数量化对比实验 - {distance_metric.upper()}")
        print(f"{'='*70}")

        # 选择要测试的位数（余弦距离跳过2-3位）
        if distance_metric == 'cosine':
            test_bits = [4, 5, 6, 7, 9, 13]
        else:
            test_bits = [2, 3, 4, 5, 6, 7, 9, 13]

        quantized_results = []
        for bits in test_bits:
            prime = PRIME_CONFIGS[bits]
            result = evaluate_quantizer_low_bit(
                prime, bits, embeddings1, embeddings2, labels,
                optimal_threshold_baseline, metric=distance_metric
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
            'experiment': 'Low-Bit Quantization Comparison - MobileNet',
            'model': 'MobileNet',
            'embedding_dimension': 128,
            'distance_metric': distance_metric,
            'timestamp': datetime.now().isoformat(),
            'num_pairs': len(labels),
            'num_genuine_pairs': int(sum(labels)),
            'num_impostor_pairs': int(len(labels) - sum(labels)),
            'baseline': baseline_results,
            'quantized': quantized_results
        }

        all_results[distance_metric] = results_data

        output_file = output_dir / f'mobilenet128d_low_bit_{distance_metric}_comparison.json'
        with open(output_file, 'w') as f:
            json.dump(results_data, f, indent=2)

        print(f"\n结果已保存到: {output_file}")

        # 生成可视化
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))

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

        # 图1: F1-Score
        ax = axes[0, 0]
        ax.plot(bits_list, f1_scores, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_f1, color='r', linestyle='--', linewidth=2, label='Baseline')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('F1-Score', fontsize=12)
        ax.set_title(f'F1-Score vs Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        if len(f1_scores) > 0 and max(f1_scores) > 0:
            ax.set_ylim([max(0, min(f1_scores) - 0.05), 1.0])

        # 图2: Accuracy
        ax = axes[0, 1]
        ax.plot(bits_list, accuracies, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_acc, color='r', linestyle='--', linewidth=2, label='Baseline')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('Accuracy', fontsize=12)
        ax.set_title(f'Accuracy vs Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        if len(accuracies) > 0 and max(accuracies) > 0:
            ax.set_ylim([max(0, min(accuracies) - 0.01), 1.0])

        # 图3: EER
        ax = axes[0, 2]
        ax.plot(bits_list, eers, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_eer, color='r', linestyle='--', linewidth=2, label='Baseline')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('EER (%)', fontsize=12)
        ax.set_title(f'EER vs Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # 图4: ROC-AUC
        ax = axes[1, 0]
        ax.plot(bits_list, aucs, 'o-', linewidth=2, markersize=8, label='Quantized')
        ax.axhline(y=baseline_auc, color='r', linestyle='--', linewidth=2, label='Baseline')
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('ROC-AUC', fontsize=12)
        ax.set_title(f'ROC-AUC vs Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        if len(aucs) > 0 and max(aucs) > 0:
            ax.set_ylim([max(0, min(aucs) - 0.05), 1.0])

        # 图5: Precision & Recall
        ax = axes[1, 1]
        ax.plot(bits_list, precisions, 'o-', linewidth=2, markersize=8, label='Precision')
        ax.plot(bits_list, recalls, 's-', linewidth=2, markersize=8, label='Recall')
        ax.axhline(y=baseline_results['optimal_metrics']['precision'],
                   color='r', linestyle='--', linewidth=1, alpha=0.5)
        ax.axhline(y=baseline_results['optimal_metrics']['recall'],
                   color='b', linestyle='--', linewidth=1, alpha=0.5)
        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('Score', fontsize=12)
        ax.set_title(f'Precision & Recall vs Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # 图6: Performance Drop
        ax = axes[1, 2]
        f1_drops = [(baseline_f1 - f1) / baseline_f1 * 100 if baseline_f1 > 0 else 0 for f1 in f1_scores]
        acc_drops = [(baseline_acc - acc) / baseline_acc * 100 if baseline_acc > 0 else 0 for acc in accuracies]

        x = np.arange(len(bits_list))
        width = 0.35

        ax.bar(x - width/2, f1_drops, width, label='F1 Drop', alpha=0.8)
        ax.bar(x + width/2, acc_drops, width, label='Accuracy Drop', alpha=0.8)

        ax.set_xlabel('Quantization Bits', fontsize=12)
        ax.set_ylabel('Performance Drop (%)', fontsize=12)
        ax.set_title(f'Performance Drop vs Bits ({distance_metric.upper()})', fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(bits_list)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        ax.axhline(y=0, color='black', linewidth=0.5)

        plt.tight_layout()
        plot_file = output_dir / f'mobilenet128d_low_bit_{distance_metric}_comparison.png'
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"  ✓ 可视化保存到: {plot_file}")
        plt.close()

    # 生成文本报告
    print("\n" + "="*70)
    print("生成文本报告")
    print("="*70)

    for distance_metric, results_data in all_results.items():
        report_file = output_dir / f'mobilenet128d_low_bit_{distance_metric}_report.txt'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*70 + "\n")
            f.write(f"低位数量化对比报告 - {distance_metric.upper()} 距离\n")
            f.write("="*70 + "\n")
            f.write(f"模型: {results_data['model']}\n")
            f.write(f"嵌入维度: {results_data['embedding_dimension']}d\n")
            f.write(f"实验时间: {results_data['timestamp']}\n")
            f.write(f"距离度量: {distance_metric}\n")
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
                       f"{result['far']*100:<10.4f} "
                       f"{result['frr']*100:<10.4f} "
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
