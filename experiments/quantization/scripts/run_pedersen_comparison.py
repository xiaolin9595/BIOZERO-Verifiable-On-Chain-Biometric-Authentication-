#!/usr/bin/env python3
"""
完整的 Pedersen 量化对比实验

对比两种策略在真实 FaceNet 特征上的性能：
1. 非对称量化 (AsymmetricQuantizer)
2. 对称量化 + 偏移映射 (SymmetricQuantizerWithOffset)

测试多种位数: 26/28/30/32-bit
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
from pedersen_quantizers import AsymmetricQuantizer, SymmetricQuantizerWithOffset, euclidean_distance


def load_facenet_model(device):
    """加载 FaceNet 模型"""
    print("[模型] 加载 FaceNet 模型...")
    mtcnn = MTCNN(image_size=160, margin=14, device=device)
    resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
    print("✓ 模型加载完成")
    return mtcnn, resnet


def extract_embeddings(mtcnn, resnet, image_dir, device):
    """提取特征向量"""
    print(f"\n[特征提取] 从 {image_dir} 提取特征...")

    images = []
    labels = []
    embeddings = []

    for person_dir in sorted(Path(image_dir).iterdir()):
        if person_dir.is_dir() and not person_dir.name.startswith('.'):
            for img_file in sorted(person_dir.glob("*.jpg")):
                if not img_file.name.startswith('._'):
                    img = Image.open(img_file)
                    img_cropped = mtcnn(img)

                    if img_cropped is not None:
                        with torch.no_grad():
                            embedding = resnet(img_cropped.unsqueeze(0)).cpu().numpy()[0]
                            embeddings.append(embedding)
                            images.append(str(img_file))
                            labels.append(person_dir.name)
                            print(f"  ✓ {person_dir.name}/{img_file.name}")

    embeddings = np.array(embeddings)
    print(f"✓ 提取完成: {len(embeddings)} 个特征向量")
    return embeddings, images, labels


def calculate_baseline_distances(embeddings):
    """计算基准距离矩阵"""
    print("\n[基准] 计算欧氏距离矩阵...")
    n = len(embeddings)
    distances = np.zeros((n, n))

    for i in range(n):
        for j in range(n):
            distances[i, j] = euclidean_distance(embeddings[i], embeddings[j])

    print(f"✓ 距离矩阵: {n}×{n}")
    print(f"  最小距离 (非零): {distances[distances > 0].min():.6f}")
    print(f"  最大距离: {distances.max():.6f}")
    print(f"  平均距离: {distances[distances > 0].mean():.6f}")

    return distances


def test_quantizer(quantizer, embeddings, distances_baseline, quantizer_name):
    """测试单个量化器"""
    print(f"\n[测试] {quantizer_name}")
    print("-" * 70)

    # 如果是对称量化器，需要先 fit
    if isinstance(quantizer, SymmetricQuantizerWithOffset):
        quantizer.fit(embeddings)

    # 量化所有向量
    embeddings_int = np.array([quantizer.quantize(emb) for emb in embeddings])

    # 反量化
    embeddings_dequant = np.array([quantizer.dequantize(emb_int) for emb_int in embeddings_int])

    # 计算量化后的距离矩阵
    n = len(embeddings)
    distances_quantized = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            distances_quantized[i, j] = euclidean_distance(
                embeddings_dequant[i],
                embeddings_dequant[j]
            )

    # 计算偏差
    distance_diff = np.abs(distances_baseline - distances_quantized)
    mean_deviation = distance_diff.mean()
    max_deviation = distance_diff.max()
    relative_deviation = mean_deviation / distances_baseline[distances_baseline > 0].mean() * 100

    # 计算量化误差统计
    quantization_errors = []
    for i in range(n):
        emb_norm = embeddings[i] / np.linalg.norm(embeddings[i])
        error = np.linalg.norm(emb_norm - embeddings_dequant[i])
        quantization_errors.append(error)

    avg_quant_error = np.mean(quantization_errors)

    # 计算SNR
    signal_powers = [np.mean(emb ** 2) for emb in embeddings]
    noise_powers = [np.mean((embeddings[i] / np.linalg.norm(embeddings[i]) - embeddings_dequant[i]) ** 2)
                    for i in range(n)]
    snrs_db = [10 * np.log10(signal_powers[i] / (noise_powers[i] + 1e-10)) for i in range(n)]
    avg_snr_db = np.mean(snrs_db)

    # 获取详细信息 (第一个向量)
    info = quantizer.get_quantization_info(embeddings[0], embeddings_int[0])

    results = {
        "quantizer_name": quantizer_name,
        "strategy": info["strategy"],
        "p": info["p"],
        "num_samples": n,
        "distance_metrics": {
            "mean_distance_deviation": float(mean_deviation),
            "max_distance_deviation": float(max_deviation),
            "relative_deviation_percent": float(relative_deviation)
        },
        "quantization_metrics": {
            "avg_euclidean_deviation": float(avg_quant_error),
            "avg_snr_db": float(avg_snr_db),
            "quantized_range": info.get("quantized_range") or info.get("pedersen_range")
        }
    }

    # 如果是对称量化，添加额外信息
    if "bits" in info:
        results["bits"] = info["bits"]
        results["scale"] = info["scale"]
        results["symmetric_range"] = info["symmetric_range"]

    # 打印结果
    print(f"  距离偏差:")
    print(f"    平均绝对偏差: {mean_deviation:.8f}")
    print(f"    最大绝对偏差: {max_deviation:.8f}")
    print(f"    相对偏差: {relative_deviation:.6f}%")
    print(f"  量化质量:")
    print(f"    平均欧氏偏差: {avg_quant_error:.8f}")
    print(f"    平均SNR: {avg_snr_db:.2f} dB")
    if "symmetric_range" in results:
        print(f"  对称范围: {results['symmetric_range']}")
    print(f"  Pedersen 范围: {results['quantization_metrics']['quantized_range']}")

    return results


def main():
    print("="*70)
    print("Pedersen 量化对比实验")
    print("="*70)
    print(f"实验时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 设备
    device = torch.device('cpu')
    print(f"设备: {device}")

    # 加载模型
    mtcnn, resnet = load_facenet_model(device)

    # 提取特征
    embeddings, images, labels = extract_embeddings(
        mtcnn, resnet, "data/test_images", device
    )

    # 计算基准距离
    distances_baseline = calculate_baseline_distances(embeddings)

    # 准备结果
    all_results = {
        "experiment": "Pedersen Quantization Comparison",
        "timestamp": datetime.now().isoformat(),
        "num_samples": len(embeddings),
        "num_identities": len(set(labels)),
        "distance_metric": "euclidean",
        "pedersen_prime": 67108859,
        "results": []
    }

    # 测试策略1: 非对称量化
    print("\n" + "="*70)
    print("策略1: 非对称量化 (AsymmetricQuantizer)")
    print("="*70)

    q_asym = AsymmetricQuantizer(p=67108859)
    result_asym = test_quantizer(
        q_asym, embeddings, distances_baseline,
        "AsymmetricQuantizer"
    )
    all_results["results"].append(result_asym)

    # 测试策略2: 对称量化 + 偏移映射 (多种位数)
    print("\n" + "="*70)
    print("策略2: 对称量化 + 偏移映射 (SymmetricQuantizerWithOffset)")
    print("="*70)

    for bits in [26, 28, 30, 32]:
        q_sym = SymmetricQuantizerWithOffset(p=67108859, bits=bits)
        result_sym = test_quantizer(
            q_sym, embeddings, distances_baseline,
            f"SymmetricQuantizer_{bits}bit"
        )
        all_results["results"].append(result_sym)

    # 保存结果
    output_file = "biozero_quantization_experiment/outputs/results/pedersen_comparison_results.json"
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    print("\n" + "="*70)
    print("实验完成")
    print("="*70)
    print(f"结果已保存到: {output_file}")

    # 打印对比总结
    print("\n" + "="*70)
    print("对比总结")
    print("="*70)
    print(f"{'量化器':<30} {'相对偏差':<15} {'SNR (dB)':<10}")
    print("-" * 70)
    for result in all_results["results"]:
        name = result["quantizer_name"]
        rel_dev = result["distance_metrics"]["relative_deviation_percent"]
        snr = result["quantization_metrics"]["avg_snr_db"]
        print(f"{name:<30} {rel_dev:>12.6f}%  {snr:>8.2f}")

    print("\n推荐:")
    # 找到相对偏差最小的
    best_result = min(all_results["results"],
                     key=lambda x: x["distance_metrics"]["relative_deviation_percent"])
    print(f"  最优量化器: {best_result['quantizer_name']}")
    print(f"  相对偏差: {best_result['distance_metrics']['relative_deviation_percent']:.6f}%")
    print(f"  SNR: {best_result['quantization_metrics']['avg_snr_db']:.2f} dB")


if __name__ == "__main__":
    main()
