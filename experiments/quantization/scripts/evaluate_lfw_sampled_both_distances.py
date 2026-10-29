#!/usr/bin/env python3
"""
在 LFW 数据集的子集上运行人脸识别性能评估
支持欧式距离和余弦相似度两种距离度量
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
from pedersen_quantizers import AsymmetricQuantizer
from sklearn.metrics import roc_curve, auc
import argparse

# 从 evaluate_recognition_performance.py 导入函数
from evaluate_recognition_performance import (
    load_facenet_model,
    find_optimal_threshold,
    compute_eer,
    compute_roc_auc,
)
from itertools import combinations


def cosine_similarity(emb1, emb2):
    """计算余弦相似度"""
    dot_product = np.dot(emb1, emb2)
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    return dot_product / (norm1 * norm2)


def compute_distances(embeddings, pairs, distance_metric='euclidean'):
    """计算距离（支持欧式距离和余弦相似度）"""
    distances = []

    if distance_metric == 'euclidean':
        for i, j in pairs:
            dist = np.linalg.norm(embeddings[i] - embeddings[j])
            distances.append(dist)
    elif distance_metric == 'cosine':
        for i, j in pairs:
            sim = cosine_similarity(embeddings[i], embeddings[j])
            # 转换为距离: distance = 1 - similarity
            dist = 1 - sim
            distances.append(dist)

    return np.array(distances)


def evaluate_quantizer_sampled(quantizer, embeddings, pairs, pair_labels, quantizer_name,
                               baseline_threshold, distance_metric='euclidean'):
    """评估量化器性能"""
    print(f"\n{'='*70}")
    print(f"[量化评估] {quantizer_name} ({distance_metric})")
    print('='*70)

    scale_factor = quantizer.scale_factor
    print(f"缩放因子: {scale_factor:,.2f}")

    # 量化嵌入向量
    print("[1/3] 量化嵌入向量...")
    embeddings_int = np.array([quantizer.quantize(emb) for emb in embeddings])

    # 计算距离
    if distance_metric == 'euclidean':
        print("[2/3] 计算整数域欧氏距离...")
        distances_int = []
        for i, j in pairs:
            diff = embeddings_int[i].astype(np.int64) - embeddings_int[j].astype(np.int64)
            dist = np.sqrt(np.sum(diff ** 2))
            distances_int.append(dist)
        distances_int = np.array(distances_int)

        # 归一化回浮点范围
        distances_normalized = distances_int / scale_factor
        evaluation_values = distances_normalized

    elif distance_metric == 'cosine':
        print("[2/3] 计算余弦相似度...")
        # 归一化到浮点范围
        embeddings_float = embeddings_int / scale_factor

        # 计算余弦相似度
        cosine_sims = []
        for i, j in pairs:
            sim = cosine_similarity(embeddings_float[i], embeddings_float[j])
            cosine_sims.append(sim)
        cosine_sims = np.array(cosine_sims)

        # 转换为距离
        evaluation_values = 1 - cosine_sims

    print(f"  距离范围: [{evaluation_values.min():.6f}, {evaluation_values.max():.6f}]")

    # 评估性能
    print("[3/3] 评估性能...")
    optimal_threshold, optimal_metrics = find_optimal_threshold(evaluation_values, pair_labels)
    eer, eer_threshold = compute_eer(evaluation_values, pair_labels)
    roc_auc_value, fpr, tpr = compute_roc_auc(evaluation_values, pair_labels)

    return {
        'quantizer_name': quantizer_name,
        'distance_metric': distance_metric,
        'scale_factor': float(scale_factor),
        'optimal_threshold': optimal_threshold,
        'optimal_metrics': optimal_metrics,
        'eer': eer,
        'eer_threshold': eer_threshold,
        'roc_auc': roc_auc_value,
    }


def sample_lfw_dataset(lfw_dir, max_identities=50, min_images_per_identity=2):
    """从 LFW 采样有多张图片的身份"""
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
    """从采样的身份中提取特征向量"""
    print(f"\n[特征提取] 从采样的身份中提取...")

    embeddings = []
    labels = []

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
                        identity_count += 1
                        total_processed += 1
            except Exception as e:
                print(f"  ✗ 错误: {img_file.name} - {e}")

        # 每处理完一个身份，打印进度
        print(f"  [{idx}/{total_identities}] {identity}: {identity_count} 张图片")

    embeddings = np.array(embeddings)
    print(f"\n✓ 提取完成: {len(embeddings)} 个样本, {len(set(labels))} 个身份\n")

    return embeddings, labels


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
    parser = argparse.ArgumentParser(description='LFW采样数据集评估 - 支持欧式距离和余弦相似度')
    parser.add_argument('--distance', type=str, choices=['euclidean', 'cosine', 'both'],
                       default='both', help='距离度量方式')
    args = parser.parse_args()

    print("="*70)
    print("人脸识别性能评估：LFW 数据集采样")
    print("="*70)
    print(f"实验时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"距离度量: {args.distance}\n")

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
        max_identities=100,
        min_images_per_identity=3
    )

    # 加载模型
    mtcnn, resnet = load_facenet_model(device)

    # 提取特征
    embeddings, labels = extract_embeddings_from_sampled_lfw(
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

        # 计算基准距离
        print(f"\n[基准评估] 浮点特征 ({distance_metric})")
        print("="*70)
        distances_baseline = compute_distances(embeddings, pairs, distance_metric)

        optimal_threshold_baseline, optimal_metrics_baseline = find_optimal_threshold(
            distances_baseline, pair_labels
        )
        eer_baseline, eer_threshold_baseline = compute_eer(distances_baseline, pair_labels)
        roc_auc_baseline, fpr_baseline, tpr_baseline = compute_roc_auc(distances_baseline, pair_labels)

        baseline_results = {
            'quantizer_name': 'Baseline_Float32',
            'distance_metric': distance_metric,
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

        print(f"\n[基准结果 - {distance_metric.upper()}]")
        print(f"  最优阈值: {optimal_threshold_baseline:.6f}")
        print(f"  F1-Score: {optimal_metrics_baseline['f1_score']:.6f}")
        print(f"  Precision: {optimal_metrics_baseline['precision']:.6f}")
        print(f"  Recall: {optimal_metrics_baseline['recall']:.6f}")
        print(f"  Accuracy: {optimal_metrics_baseline['accuracy']:.6f}")
        print(f"  EER: {eer_baseline*100:.4f}%")
        print(f"  ROC-AUC: {roc_auc_baseline:.6f}")

        # 测试量化器
        quantizer = AsymmetricQuantizer(p=67108859)  # 26-bit

        quantized_result = evaluate_quantizer_sampled(
            quantizer, embeddings, pairs, pair_labels,
            "AsymmetricQuantizer_26bit",
            optimal_threshold_baseline,
            distance_metric
        )

        print(f"\n[量化结果 - {distance_metric.upper()}]")
        print(f"  最优阈值: {quantized_result['optimal_threshold']:.6f}")
        print(f"  F1-Score: {quantized_result['optimal_metrics']['f1_score']:.6f}")
        print(f"  Precision: {quantized_result['optimal_metrics']['precision']:.6f}")
        print(f"  Recall: {quantized_result['optimal_metrics']['recall']:.6f}")
        print(f"  Accuracy: {quantized_result['optimal_metrics']['accuracy']:.6f}")
        print(f"  EER: {quantized_result['eer']*100:.4f}%")
        print(f"  ROC-AUC: {quantized_result['roc_auc']:.6f}")

        # 计算性能变化
        f1_change = (quantized_result['optimal_metrics']['f1_score'] - baseline_results['optimal_metrics']['f1_score']) / baseline_results['optimal_metrics']['f1_score'] * 100
        eer_change = (quantized_result['eer'] - baseline_results['eer']) / baseline_results['eer'] * 100
        auc_change = (quantized_result['roc_auc'] - baseline_results['roc_auc']) / baseline_results['roc_auc'] * 100

        print(f"\n[性能变化 - {distance_metric.upper()}]")
        print(f"  F1变化: {f1_change:+.4f}%")
        print(f"  EER变化: {eer_change:+.4f}%")
        print(f"  AUC变化: {auc_change:+.4f}%")

        # 保存结果
        results_data = {
            'experiment': f'Face Recognition Performance Evaluation (LFW Sampled) - {distance_metric.upper()}',
            'timestamp': datetime.now().isoformat(),
            'distance_metric': distance_metric,
            'num_samples': len(embeddings),
            'num_identities': len(set(labels)),
            'num_pairs': len(pairs),
            'num_genuine_pairs': int(sum(pair_labels)),
            'num_impostor_pairs': int(len(pair_labels) - sum(pair_labels)),
            'baseline': baseline_results,
            'quantized': quantized_result
        }

        all_results[distance_metric] = results_data

    # 保存结果到文件
    output_dir = Path("biozero_quantization_experiment/outputs/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    for distance_metric, results_data in all_results.items():
        output_file = output_dir / f'lfw_sampled_{distance_metric}_evaluation.json'
        with open(output_file, 'w') as f:
            json.dump(results_data, f, indent=2)

        print(f"\n{distance_metric.upper()} 结果已保存到: {output_file}")

        # 生成文本报告
        report_file = output_dir / f'lfw_sampled_{distance_metric}_report.txt'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*70 + "\n")
            f.write(f"LFW采样数据集评估报告 - {distance_metric.upper()} 距离\n")
            f.write("="*70 + "\n")
            f.write(f"实验时间: {results_data['timestamp']}\n")
            f.write(f"距离度量: {distance_metric}\n")
            f.write(f"样本数量: {results_data['num_samples']}\n")
            f.write(f"身份数量: {results_data['num_identities']}\n")
            f.write(f"图像对数量: {results_data['num_pairs']}\n")
            f.write(f"正样本对: {results_data['num_genuine_pairs']}\n")
            f.write(f"负样本对: {results_data['num_impostor_pairs']}\n\n")

            baseline = results_data['baseline']
            quantized = results_data['quantized']

            f.write("[基准性能]\n")
            f.write(f"  准确率: {baseline['optimal_metrics']['accuracy']:.6f}\n")
            f.write(f"  F1分数: {baseline['optimal_metrics']['f1_score']:.6f}\n")
            f.write(f"  精确率: {baseline['optimal_metrics']['precision']:.6f}\n")
            f.write(f"  召回率: {baseline['optimal_metrics']['recall']:.6f}\n")
            f.write(f"  ROC-AUC: {baseline['roc_auc']:.6f}\n")
            f.write(f"  EER: {baseline['eer']*100:.4f}%\n")
            f.write(f"  最优阈值: {baseline['optimal_threshold']:.6f}\n\n")

            f.write("[量化性能 (26-bit)]\n")
            f.write(f"  准确率: {quantized['optimal_metrics']['accuracy']:.6f}\n")
            f.write(f"  F1分数: {quantized['optimal_metrics']['f1_score']:.6f}\n")
            f.write(f"  精确率: {quantized['optimal_metrics']['precision']:.6f}\n")
            f.write(f"  召回率: {quantized['optimal_metrics']['recall']:.6f}\n")
            f.write(f"  ROC-AUC: {quantized['roc_auc']:.6f}\n")
            f.write(f"  EER: {quantized['eer']*100:.4f}%\n")
            f.write(f"  最优阈值: {quantized['optimal_threshold']:.6f}\n\n")

            f1_change = (quantized['optimal_metrics']['f1_score'] - baseline['optimal_metrics']['f1_score']) / baseline['optimal_metrics']['f1_score'] * 100
            acc_change = (quantized['optimal_metrics']['accuracy'] - baseline['optimal_metrics']['accuracy']) / baseline['optimal_metrics']['accuracy'] * 100
            eer_change = (quantized['eer'] - baseline['eer']) / baseline['eer'] * 100

            f.write("[性能变化]\n")
            f.write(f"  准确率变化: {acc_change:+.4f}%\n")
            f.write(f"  F1分数变化: {f1_change:+.4f}%\n")
            f.write(f"  EER变化: {eer_change:+.4f}%\n")

        print(f"{distance_metric.upper()} 报告已保存到: {report_file}")

    print("\n" + "="*70)
    print("评估完成")
    print("="*70)


if __name__ == "__main__":
    main()
