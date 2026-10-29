#!/usr/bin/env python3
"""
在 LFW 数据集的子集上运行人脸识别性能评估

为了节省时间，只选择有多张图片的身份
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
from sklearn.metrics import roc_curve, auc, confusion_matrix
import matplotlib.pyplot as plt
from itertools import combinations

# 从 evaluate_recognition_performance.py 导入函数
from evaluate_recognition_performance import (
    load_facenet_model,
    compute_distances,
    evaluate_at_threshold,
    find_optimal_threshold,
    compute_eer,
    compute_roc_auc,
    evaluate_quantizer,
    plot_comparison_results
)


def sample_lfw_dataset(lfw_dir, max_identities=50, min_images_per_identity=2):
    """
    从 LFW 采样有多张图片的身份

    Args:
        lfw_dir: LFW数据集根目录
        max_identities: 最多采样多少个身份
        min_images_per_identity: 每个身份至少需要多少张图片

    Returns:
        sampled_identities: list of (identity_name, num_images)
    """
    print(f"[采样] 从 LFW 数据集采样...")
    print(f"  根目录: {lfw_dir}")
    print(f"  最多采样: {max_identities} 个身份")
    print(f"  每个身份至少: {min_images_per_identity} 张图片\n")

    lfw_path = Path(lfw_dir)

    # 统计每个身份的图片数
    identity_stats = {}

    for person_dir in lfw_path.iterdir():
        if person_dir.is_dir() and not person_dir.name.startswith('.'):
            images = list(person_dir.glob("*.jpg"))
            if len(images) >= min_images_per_identity:
                identity_stats[person_dir.name] = len(images)

    # 按图片数排序，选择图片最多的身份
    sorted_identities = sorted(identity_stats.items(), key=lambda x: -x[1])
    sampled = sorted_identities[:max_identities]

    print(f"  找到 {len(identity_stats)} 个身份有 ≥{min_images_per_identity} 张图片")
    print(f"  采样其中前 {len(sampled)} 个\n")

    print("  采样的身份 (前10个):")
    for i, (name, count) in enumerate(sampled[:10]):
        print(f"    {i+1:2d}. {name:<30s} {count} 张")
    if len(sampled) > 10:
        print(f"    ...")

    return [name for name, _ in sampled]


def extract_embeddings_from_sampled_lfw(mtcnn, resnet, lfw_dir, sampled_identities, device):
    """
    从采样的身份中提取特征向量
    """
    print(f"\n[特征提取] 从采样的身份中提取...")

    embeddings = []
    labels = []
    image_paths = []

    lfw_path = Path(lfw_dir)

    total_processed = 0
    total_identities = len(sampled_identities)

    for idx, identity in enumerate(sampled_identities, 1):
        person_dir = lfw_path / identity

        if not person_dir.exists():
            continue

        identity_count = 0
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
                        identity_count += 1
                        total_processed += 1
            except Exception as e:
                print(f"  ✗ 错误: {img_file.name} - {e}")

        # 每处理完一个身份，打印进度
        print(f"  [{idx}/{total_identities}] {identity}: {identity_count} 张图片")

    embeddings = np.array(embeddings)
    print(f"\n✓ 提取完成: {len(embeddings)} 个样本, {len(set(labels))} 个身份\n")

    return embeddings, labels, image_paths


def generate_pairs_and_labels(embeddings, labels):
    """生成所有可能的图像对及其真实标签"""
    print("[对生成] 生成所有图像对...")

    pairs = []
    pair_labels = []

    n = len(embeddings)

    for i, j in combinations(range(n), 2):
        pairs.append((i, j))
        pair_labels.append(1 if labels[i] == labels[j] else 0)

    genuine_pairs = sum(pair_labels)
    impostor_pairs = len(pair_labels) - genuine_pairs

    print(f"  总对数: {len(pairs)}")
    print(f"  正样本对 (同一人): {genuine_pairs}")
    print(f"  负样本对 (不同人): {impostor_pairs}")

    if genuine_pairs > 0:
        print(f"  正负比例: 1:{impostor_pairs/genuine_pairs:.2f}\n")
    else:
        print(f"  ⚠️  警告: 没有正样本对！\n")

    return pairs, np.array(pair_labels)


def main():
    print("="*70)
    print("人脸识别性能评估：LFW 数据集采样")
    print("="*70)
    print(f"实验时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 设备
    device = torch.device('cpu')
    print(f"设备: {device}\n")

    # LFW 数据集路径
    lfw_dir = "data/lfw/lfw/lfw-deepfunneled"

    if not Path(lfw_dir).exists():
        print(f"✗ 错误: LFW 数据集未找到: {lfw_dir}")
        print("请先运行: python3 biozero_quantization_experiment/scripts/download_lfw.py")
        return

    # 采样身份
    sampled_identities = sample_lfw_dataset(
        lfw_dir,
        max_identities=100,  # 采样30个身份（约150-300张图片）
        min_images_per_identity=3  # 每个身份至少3张图片
    )

    # 加载模型
    mtcnn, resnet = load_facenet_model(device)

    # 提取特征
    embeddings, labels, image_paths = extract_embeddings_from_sampled_lfw(
        mtcnn, resnet, lfw_dir, sampled_identities, device
    )

    # 生成图像对
    pairs, pair_labels = generate_pairs_and_labels(embeddings, labels)

    # 计算基准距离
    print("[基准评估] 浮点特征 (无量化)")
    print("="*70)
    distances_baseline = compute_distances(embeddings, pairs)

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
        }
    }

    print(f"\n最优阈值: {optimal_threshold_baseline:.6f}")
    print(f"F1-Score: {optimal_metrics_baseline['f1_score']:.6f}")
    print(f"Precision: {optimal_metrics_baseline['precision']:.6f}")
    print(f"Recall: {optimal_metrics_baseline['recall']:.6f}")
    print(f"Accuracy: {optimal_metrics_baseline['accuracy']:.6f}")
    print(f"EER: {eer_baseline*100:.4f}%")
    print(f"ROC-AUC: {roc_auc_baseline:.6f}")

    # 测试量化器（使用基准阈值，直接在整数域计算）
    print(f"\n{'='*70}")
    print(f"使用基准浮点阈值 {optimal_threshold_baseline:.6f}")
    print(f"将在整数域转换并评估")
    print(f"{'='*70}")

    quantizers = [
        (AsymmetricQuantizer(p=67108859), "AsymmetricQuantizer"),
    ]

    quantized_results = []
    for quantizer, name in quantizers:
        result = evaluate_quantizer(quantizer, embeddings, pairs, pair_labels, name, optimal_threshold_baseline)
        quantized_results.append(result)

    # 生成对比报告
    print("\n" + "="*70)
    print("对比总结")
    print("="*70)

    print(f"\n{'量化器':<30} {'F1':<10} {'Precision':<10} {'Recall':<10} {'EER(%)':<10} {'ROC-AUC':<10}")
    print("-"*70)

    print(f"{'Baseline_Float32':<30} "
          f"{baseline_results['optimal_metrics']['f1_score']:<10.6f} "
          f"{baseline_results['optimal_metrics']['precision']:<10.6f} "
          f"{baseline_results['optimal_metrics']['recall']:<10.6f} "
          f"{baseline_results['eer']*100:<10.4f} "
          f"{baseline_results['roc_auc']:<10.6f}")

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
        'experiment': 'Face Recognition Performance Evaluation (LFW Sampled)',
        'timestamp': datetime.now().isoformat(),
        'num_samples': len(embeddings),
        'num_identities': len(set(labels)),
        'num_pairs': len(pairs),
        'num_genuine_pairs': int(sum(pair_labels)),
        'num_impostor_pairs': int(len(pair_labels) - sum(pair_labels)),
        'baseline': baseline_results,
        'quantized': quantized_results
    }

    output_file = output_dir / 'lfw_recognition_performance_evaluation.json'
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
