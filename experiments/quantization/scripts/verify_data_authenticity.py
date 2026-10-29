#!/usr/bin/env python3
"""
验证实验数据真实性 - 重新运行并输出详细中间结果
"""

import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
import numpy as np
from PIL import Image
from pathlib import Path
import json

print("="*70)
print("数据真实性验证 - 重新运行实验并输出详细过程")
print("="*70)

# 1. 加载模型
print("\n[步骤 1] 加载模型...")
device = torch.device('cpu')
mtcnn = MTCNN(image_size=160, margin=14, device=device)
resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
print("✓ 模型加载完成")

# 2. 加载测试图像
print("\n[步骤 2] 加载测试图像...")
test_image_dir = Path("data/test_images")
images = []
labels = []

for person_dir in sorted(test_image_dir.iterdir()):
    if person_dir.is_dir() and not person_dir.name.startswith('.'):
        for img_file in sorted(person_dir.glob("*.jpg")):
            if not img_file.name.startswith('._'):  # 跳过macOS隐藏文件
                images.append(img_file)
                labels.append(person_dir.name)
                print(f"  发现: {person_dir.name}/{img_file.name}")

print(f"\n✓ 共找到 {len(images)} 张有效图像")

# 3. 提取特征向量
print("\n[步骤 3] 提取特征向量...")
embeddings_float = []

for i, img_path in enumerate(images):
    img = Image.open(img_path)
    img_cropped = mtcnn(img)

    if img_cropped is not None:
        with torch.no_grad():
            embedding = resnet(img_cropped.unsqueeze(0)).cpu().numpy()[0]
            embeddings_float.append(embedding)
            print(f"  [{i+1}/{len(images)}] {labels[i]}: 特征向量维度={embedding.shape}, L2范数={np.linalg.norm(embedding):.4f}")
    else:
        print(f"  [{i+1}/{len(images)}] {labels[i]}: 未检测到人脸，跳过")

embeddings_float = np.array(embeddings_float)
print(f"\n✓ 成功提取 {len(embeddings_float)} 个特征向量")

# 4. 计算基准距离矩阵
print("\n[步骤 4] 计算基准距离矩阵 (欧氏距离)...")
n = len(embeddings_float)
distances_baseline = np.zeros((n, n))

print(f"\n距离矩阵 ({n}×{n}):")
print("     ", end="")
for i in range(n):
    print(f"ID{i:<8}", end="")
print()

for i in range(n):
    print(f"ID{i}  ", end="")
    for j in range(n):
        dist = np.sqrt(np.sum((embeddings_float[i] - embeddings_float[j]) ** 2))
        distances_baseline[i, j] = dist
        print(f"{dist:<8.4f}", end="")
    print()

print(f"\n基准距离统计:")
print(f"  最小距离 (非零): {distances_baseline[distances_baseline > 0].min():.6f}")
print(f"  最大距离: {distances_baseline.max():.6f}")
print(f"  平均距离: {distances_baseline[distances_baseline > 0].mean():.6f}")

# 5. 量化实验 - 16-bit (详细验证)
print("\n[步骤 5] 16-bit量化详细验证...")

bits = 16
print(f"\n量化参数: {bits}-bit")

# 5.1 计算量化参数
embeddings_norm = embeddings_float / np.linalg.norm(embeddings_float, axis=1, keepdims=True)
max_val = np.abs(embeddings_norm).max()
scale = (2 ** (bits - 1) - 1) / max_val

print(f"  最大归一化值: {max_val:.6f}")
print(f"  缩放因子: {scale:.2f}")
print(f"  量化范围: [{-(2**(bits-1))}, {2**(bits-1)-1}]")

# 5.2 量化第一个特征向量（详细过程）
print(f"\n详细验证第一个特征向量 (ID0):")
emb0 = embeddings_float[0]
print(f"  原始向量前5维: {emb0[:5]}")
print(f"  原始向量L2范数: {np.linalg.norm(emb0):.6f}")

emb0_norm = emb0 / np.linalg.norm(emb0)
print(f"  归一化后前5维: {emb0_norm[:5]}")
print(f"  归一化后L2范数: {np.linalg.norm(emb0_norm):.6f}")

emb0_scaled = emb0_norm * scale
print(f"  缩放后前5维: {emb0_scaled[:5]}")

emb0_int = np.round(emb0_scaled).astype(np.int32)
print(f"  量化后前5维 (整数): {emb0_int[:5]}")
print(f"  量化后范围: [{emb0_int.min()}, {emb0_int.max()}]")

emb0_dequant = emb0_int.astype(np.float32) / scale
print(f"  反量化后前5维: {emb0_dequant[:5]}")
print(f"  反量化后L2范数: {np.linalg.norm(emb0_dequant):.6f}")

# 5.3 计算量化误差
quant_error = np.sqrt(np.sum((emb0_norm - emb0_dequant) ** 2))
print(f"  欧氏距离偏差: {quant_error:.8f}")

signal_power = np.mean(emb0_norm ** 2)
noise_power = np.mean((emb0_norm - emb0_dequant) ** 2)
snr_db = 10 * np.log10(signal_power / (noise_power + 1e-10))
print(f"  信噪比 (SNR): {snr_db:.2f} dB")

# 5.4 量化所有向量并计算距离矩阵
print(f"\n量化所有向量...")
embeddings_int = []
for emb in embeddings_float:
    emb_norm = emb / np.linalg.norm(emb)
    emb_scaled = emb_norm * scale
    emb_int = np.round(emb_scaled).astype(np.int32)
    embeddings_int.append(emb_int)

embeddings_int = np.array(embeddings_int)
embeddings_dequant = embeddings_int.astype(np.float32) / scale

print(f"\n计算量化后的距离矩阵...")
distances_quantized = np.zeros((n, n))

print(f"\n量化后距离矩阵 ({n}×{n}):")
print("     ", end="")
for i in range(n):
    print(f"ID{i:<8}", end="")
print()

for i in range(n):
    print(f"ID{i}  ", end="")
    for j in range(n):
        dist = np.sqrt(np.sum((embeddings_dequant[i] - embeddings_dequant[j]) ** 2))
        distances_quantized[i, j] = dist
        print(f"{dist:<8.4f}", end="")
    print()

# 5.5 距离偏差分析
print(f"\n距离偏差分析:")
distance_diff = distances_baseline - distances_quantized
print(f"\n距离差异矩阵 (基准 - 量化):")
print("     ", end="")
for i in range(n):
    print(f"ID{i:<10}", end="")
print()

for i in range(n):
    print(f"ID{i}  ", end="")
    for j in range(n):
        print(f"{distance_diff[i, j]:<10.6f}", end="")
    print()

mean_deviation = np.mean(np.abs(distance_diff))
max_deviation = np.max(np.abs(distance_diff))
relative_deviation = mean_deviation / distances_baseline[distances_baseline > 0].mean() * 100

print(f"\n距离偏差统计:")
print(f"  平均绝对偏差: {mean_deviation:.8f}")
print(f"  最大绝对偏差: {max_deviation:.8f}")
print(f"  相对偏差: {relative_deviation:.6f}%")

# 6. 与之前结果对比
print("\n[步骤 6] 与之前结果对比...")
with open("biozero_quantization_experiment/outputs/results/poc_results.json", 'r') as f:
    previous_results = json.load(f)

for result in previous_results['results']:
    if result['bits'] == 16:
        print(f"\n16-bit量化结果对比:")
        print(f"  之前的平均距离偏差: {result['mean_distance_deviation']:.8f}")
        print(f"  本次的平均距离偏差: {mean_deviation:.8f}")
        print(f"  差异: {abs(result['mean_distance_deviation'] - mean_deviation):.10f}")

        print(f"\n  之前的相对偏差: {result['relative_deviation_percent']:.6f}%")
        print(f"  本次的相对偏差: {relative_deviation:.6f}%")

        if abs(result['mean_distance_deviation'] - mean_deviation) < 1e-6:
            print(f"\n✅ 数据一致！差异在数值精度范围内")
        else:
            print(f"\n⚠️  数据存在差异，可能是:")
            print(f"     1. 随机种子不同")
            print(f"     2. 计算顺序不同导致的浮点误差")
            print(f"     3. 图像加载顺序不同")

print("\n" + "="*70)
print("验证完成")
print("="*70)
