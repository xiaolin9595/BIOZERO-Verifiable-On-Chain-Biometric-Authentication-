#!/usr/bin/env python3
"""
BioZero量化实验 - 简化版概念验证
使用facenet-pytorch自带的测试图像进行快速验证
"""

import torch
from facenet_pytorch import MTCNN, InceptionResnetV1, fixed_image_standardization
import numpy as np
from PIL import Image
import os
import json
from datetime import datetime
from pathlib import Path

# 量化器类
class SymmetricQuantizer:
    """对称量化器 (与BioZero协议一致)"""

    def __init__(self, bits=16):
        self.bits = bits
        self.scale = None

    def fit(self, embeddings):
        """计算量化参数"""
        # L2归一化
        embeddings_norm = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        max_val = np.abs(embeddings_norm).max()

        # 计算缩放因子
        self.scale = (2 ** (self.bits - 1) - 1) / max_val
        return self

    def quantize(self, embedding):
        """量化单个向量"""
        # L2归一化
        embedding_norm = embedding / np.linalg.norm(embedding)

        # 缩放并量化
        embedding_scaled = embedding_norm * self.scale
        int_min = -(2 ** (self.bits - 1))
        int_max = 2 ** (self.bits - 1) - 1
        embedding_clipped = np.clip(embedding_scaled, int_min, int_max)
        embedding_int = np.round(embedding_clipped).astype(np.int32)

        return embedding_int

    def dequantize(self, embedding_int):
        """反量化"""
        return embedding_int.astype(np.float32) / self.scale

    def quantization_error(self, embedding_original, embedding_quantized):
        """计算量化误差 (使用欧氏距离)"""
        embedding_dequant = self.dequantize(embedding_quantized)

        # MSE
        mse = np.mean((embedding_original - embedding_dequant) ** 2)

        # 欧氏距离偏差 (BioZero核心指标)
        euclidean_deviation = np.sqrt(np.sum((embedding_original - embedding_dequant) ** 2))

        # SNR
        signal_power = np.mean(embedding_original ** 2)
        noise_power = np.mean((embedding_original - embedding_dequant) ** 2)
        snr_db = 10 * np.log10(signal_power / (noise_power + 1e-10))

        return {
            'mse': float(mse),
            'euclidean_deviation': float(euclidean_deviation),
            'snr_db': float(snr_db)
        }


def euclidean_distance(emb1, emb2):
    """计算欧氏距离 (BioZero使用)"""
    return np.sqrt(np.sum((emb1 - emb2) ** 2))


def run_poc_experiment():
    """运行概念验证实验"""

    print("="*70)
    print("BioZero量化实验 - 概念验证 (使用测试图像)")
    print("="*70)

    device = torch.device('cpu')
    print(f"\n设备: {device}")

    # 1. 加载模型
    print("\n[1/6] 加载FaceNet模型...")
    mtcnn = MTCNN(image_size=160, margin=14, device=device)
    resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
    print("✓ 模型加载完成")

    # 2. 加载测试图像
    print("\n[2/6] 加载测试图像...")
    test_image_dir = Path("data/test_images")

    if not test_image_dir.exists():
        print(f"✗ 测试图像目录不存在: {test_image_dir}")
        print("请先运行 python tests/actions_test.py 生成测试数据")
        return False

    # 收集所有测试图像
    images = []
    labels = []
    for person_dir in test_image_dir.iterdir():
        if person_dir.is_dir() and not person_dir.name.startswith('.'):
            for img_file in person_dir.glob("*.jpg"):
                images.append(img_file)
                labels.append(person_dir.name)

    print(f"✓ 找到 {len(images)} 张测试图像, {len(set(labels))} 个人物")

    # 3. 提取特征向量 (浮点基准)
    print("\n[3/6] 提取浮点特征向量 (基准)...")
    embeddings_float = []

    for img_path in images:
        try:
            img = Image.open(img_path)
            img_cropped = mtcnn(img)

            if img_cropped is not None:
                with torch.no_grad():
                    embedding = resnet(img_cropped.unsqueeze(0)).cpu().numpy()[0]
                    embeddings_float.append(embedding)
            else:
                print(f"  跳过 (未检测到人脸): {img_path.name}")
                labels.pop(len(embeddings_float))

        except Exception as e:
            print(f"  错误: {img_path.name}: {e}")

    embeddings_float = np.array(embeddings_float)
    print(f"✓ 成功提取 {len(embeddings_float)} 个特征向量 (512维)")

    # 4. 计算基准距离矩阵
    print("\n[4/6] 计算基准欧氏距离矩阵...")
    n = len(embeddings_float)
    distances_baseline = np.zeros((n, n))

    for i in range(n):
        for j in range(n):
            distances_baseline[i, j] = euclidean_distance(embeddings_float[i], embeddings_float[j])

    print(f"✓ 距离范围: [{distances_baseline[distances_baseline > 0].min():.4f}, {distances_baseline.max():.4f}]")

    # 5. 量化实验
    print("\n[5/6] 运行量化实验...")
    results = []

    for bits in [8, 12, 16]:
        print(f"\n  测试 {bits}-bit 量化...")

        # 量化所有特征
        quantizer = SymmetricQuantizer(bits=bits)
        quantizer.fit(embeddings_float)

        embeddings_int = np.array([quantizer.quantize(emb) for emb in embeddings_float])
        embeddings_dequant = np.array([quantizer.dequantize(emb_int) for emb_int in embeddings_int])

        # 计算量化后的距离矩阵
        distances_quantized = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                distances_quantized[i, j] = euclidean_distance(embeddings_dequant[i], embeddings_dequant[j])

        # 分析距离偏差
        distance_deviations = np.abs(distances_baseline - distances_quantized)
        mean_deviation = np.mean(distance_deviations)
        max_deviation = np.max(distance_deviations)

        # 计算量化误差统计
        quantization_errors = []
        for i in range(n):
            error = quantizer.quantization_error(embeddings_float[i], embeddings_int[i])
            quantization_errors.append(error)

        avg_mse = np.mean([e['mse'] for e in quantization_errors])
        avg_euclidean_dev = np.mean([e['euclidean_deviation'] for e in quantization_errors])
        avg_snr = np.mean([e['snr_db'] for e in quantization_errors])

        result = {
            'bits': bits,
            'mean_distance_deviation': float(mean_deviation),
            'max_distance_deviation': float(max_deviation),
            'relative_deviation_percent': float(mean_deviation / distances_baseline[distances_baseline > 0].mean() * 100),
            'avg_mse': float(avg_mse),
            'avg_euclidean_deviation': float(avg_euclidean_dev),
            'avg_snr_db': float(avg_snr)
        }
        results.append(result)

        print(f"    平均距离偏差: {mean_deviation:.6f}")
        print(f"    相对偏差: {result['relative_deviation_percent']:.3f}%")
        print(f"    平均欧氏距离偏差: {avg_euclidean_dev:.6f}")
        print(f"    平均SNR: {avg_snr:.2f} dB")

    # 6. 保存结果
    print("\n[6/6] 保存结果...")
    output_dir = Path("biozero_quantization_experiment/outputs/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "poc_results.json"

    output_data = {
        'experiment': 'BioZero Quantization POC',
        'timestamp': datetime.now().isoformat(),
        'num_samples': n,
        'num_identities': len(set(labels)),
        'distance_metric': 'euclidean',
        'results': results
    }

    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"✓ 结果已保存至: {output_file}")

    # 打印总结
    print("\n" + "="*70)
    print("实验总结:")
    print("="*70)
    print(f"样本数量: {n}")
    print(f"特征维度: 512")
    print(f"距离度量: 欧氏距离 (BioZero协议)")
    print("\n量化性能:")
    print("-"*70)
    print(f"{'位数':<8} {'平均偏差':<12} {'相对偏差%':<12} {'SNR (dB)':<10}")
    print("-"*70)
    for r in results:
        print(f"{r['bits']:<8} {r['mean_distance_deviation']:<12.6f} {r['relative_deviation_percent']:<12.3f} {r['avg_snr_db']:<10.2f}")
    print("="*70)

    return True


if __name__ == "__main__":
    success = run_poc_experiment()
    exit(0 if success else 1)
