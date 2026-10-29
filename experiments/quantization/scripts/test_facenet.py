#!/usr/bin/env python3
"""
快速测试脚本：验证FaceNet模型加载和特征提取
"""

import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
import numpy as np
from PIL import Image
import os

def test_facenet():
    """测试FaceNet模型加载和基本功能"""

    print("="*60)
    print("BioZero量化实验 - FaceNet模型测试")
    print("="*60)

    # 检查设备
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\n1. 设备: {device}")

    # 加载MTCNN (人脸检测)
    print("\n2. 加载MTCNN人脸检测模型...")
    try:
        mtcnn = MTCNN(
            image_size=160,
            margin=14,
            device=device,
            selection_method='center_weighted_size'
        )
        print("   ✓ MTCNN加载成功")
    except Exception as e:
        print(f"   ✗ MTCNN加载失败: {e}")
        return False

    # 加载InceptionResnetV1 (特征提取)
    print("\n3. 加载InceptionResnetV1模型 (VGGFace2)...")
    try:
        resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
        print("   ✓ InceptionResnetV1加载成功")
        print(f"   ✓ 模型参数量: {sum(p.numel() for p in resnet.parameters()):,}")
    except Exception as e:
        print(f"   ✗ InceptionResnetV1加载失败: {e}")
        return False

    # 测试特征提取
    print("\n4. 测试特征提取...")
    try:
        # 创建测试图像 (160x160 RGB)
        test_img = torch.randn(1, 3, 160, 160).to(device)

        with torch.no_grad():
            embedding = resnet(test_img)

        print(f"   ✓ 特征向量维度: {embedding.shape}")
        print(f"   ✓ 特征向量范围: [{embedding.min():.4f}, {embedding.max():.4f}]")
        print(f"   ✓ 特征向量L2范数: {torch.norm(embedding, p=2):.4f}")

        # 验证输出维度
        assert embedding.shape == (1, 512), f"期望维度 (1, 512), 实际 {embedding.shape}"
        print("   ✓ 维度验证通过")

    except Exception as e:
        print(f"   ✗ 特征提取失败: {e}")
        return False

    # 测试欧氏距离计算
    print("\n5. 测试欧氏距离计算...")
    try:
        # 生成两个特征向量
        emb1 = torch.randn(512).to(device)
        emb2 = torch.randn(512).to(device)

        # 欧氏距离 (BioZero使用)
        euclidean_dist = torch.sqrt(torch.sum((emb1 - emb2) ** 2)).item()

        print(f"   ✓ 欧氏距离: {euclidean_dist:.4f}")

        # L2归一化后的距离
        emb1_norm = emb1 / torch.norm(emb1, p=2)
        emb2_norm = emb2 / torch.norm(emb2, p=2)
        euclidean_dist_norm = torch.sqrt(torch.sum((emb1_norm - emb2_norm) ** 2)).item()

        print(f"   ✓ L2归一化后欧氏距离: {euclidean_dist_norm:.4f}")

    except Exception as e:
        print(f"   ✗ 距离计算失败: {e}")
        return False

    # 测试量化
    print("\n6. 测试简单量化...")
    try:
        # 16-bit对称量化
        emb_np = emb1.cpu().numpy()
        emb_normalized = emb_np / np.linalg.norm(emb_np)

        bits = 16
        scale = 2 ** (bits - 1) - 1
        emb_quantized = np.round(emb_normalized * scale).astype(np.int32)
        emb_dequantized = emb_quantized.astype(np.float32) / scale

        # 量化误差
        quantization_error = np.sqrt(np.sum((emb_normalized - emb_dequantized) ** 2))

        print(f"   ✓ 量化位数: {bits}-bit")
        print(f"   ✓ 量化范围: [{emb_quantized.min()}, {emb_quantized.max()}]")
        print(f"   ✓ 量化误差: {quantization_error:.6f}")

    except Exception as e:
        print(f"   ✗ 量化测试失败: {e}")
        return False

    print("\n" + "="*60)
    print("✓ 所有测试通过！")
    print("="*60)

    return True

if __name__ == "__main__":
    success = test_facenet()
    exit(0 if success else 1)
