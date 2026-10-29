#!/usr/bin/env python3
"""
Pedersen 兼容的量化器实现
包含两种策略：
1. 非对称量化 (AsymmetricQuantizer) - DeepFace 风格
2. 对称量化 + 偏移映射 (SymmetricQuantizerWithOffset) - FaceNet 适配
"""

import numpy as np
from typing import Union, Tuple


class AsymmetricQuantizer:
    """
    策略1: 非对称量化

    将浮点范围 [-1, 1] 直接映射到 [0, p-1]
    这是 DeepFace 实现使用的方法

    优点:
    - 直接映射，无需额外转换
    - 充分利用量化范围
    - 实现简单

    缺点:
    - 打破对称性 (0 不在中点)
    - 与传统对称量化不兼容
    """

    def __init__(self, p: int = 67108859):
        """
        初始化非对称量化器

        Args:
            p: Pedersen 承诺的质数模数 (默认 67108859)
        """
        self.p = p
        self.name = "AsymmetricQuantizer"

        # FaceNet 输出归一化后的范围 (实际观察值)
        # 可以从数据集学习，这里使用保守估计
        self.float_min = -1.0
        self.float_max = 1.0

        # 缩放因子: 将 [-1, 1] 映射到 [0, p-1]
        self.scale_factor = (p - 1) / (self.float_max - self.float_min)

        print(f"[{self.name}] 初始化完成")
        print(f"  质数 p = {self.p:,}")
        print(f"  浮点范围: [{self.float_min}, {self.float_max}]")
        print(f"  整数范围: [0, {self.p - 1:,}]")
        print(f"  缩放因子: {self.scale_factor:.2f}")

    def quantize(self, embedding: np.ndarray) -> np.ndarray:
        """
        量化单个特征向量

        Args:
            embedding: 浮点特征向量 (512维)

        Returns:
            量化后的整数向量，范围 [0, p-1]
        """
        # 步骤1: L2归一化
        embedding_norm = embedding / np.linalg.norm(embedding)

        # 步骤2: 裁剪到有效范围
        embedding_clipped = np.clip(embedding_norm, self.float_min, self.float_max)

        # 步骤3: 缩放到 [0, p-1]
        # 映射公式: x_int = (x_float - min) / (max - min) * (p - 1)
        embedding_scaled = (embedding_clipped - self.float_min) * self.scale_factor

        # 步骤4: 四舍五入
        embedding_int = np.round(embedding_scaled).astype(np.int64)

        # 步骤5: 确保在有效范围内 (防止舍入误差)
        embedding_int = np.clip(embedding_int, 0, self.p - 1)

        return embedding_int

    def dequantize(self, embedding_int: np.ndarray) -> np.ndarray:
        """
        反量化：整数 → 浮点

        Args:
            embedding_int: 量化后的整数向量

        Returns:
            反量化后的浮点向量
        """
        # 步骤1: 裁剪到有效范围
        embedding_clipped = np.clip(embedding_int, 0, self.p - 1)

        # 步骤2: 反向缩放
        # 映射公式: x_float = x_int / (p - 1) * (max - min) + min
        embedding_scaled = embedding_clipped.astype(np.float64) / self.scale_factor

        # 步骤3: 偏移回原始范围
        embedding_float = embedding_scaled + self.float_min

        return embedding_float.astype(np.float32)

    def get_quantization_info(self, embedding: np.ndarray, embedding_int: np.ndarray) -> dict:
        """
        获取量化信息用于分析

        Args:
            embedding: 原始浮点向量
            embedding_int: 量化后的整数向量

        Returns:
            包含量化统计信息的字典
        """
        embedding_norm = embedding / np.linalg.norm(embedding)
        embedding_dequant = self.dequantize(embedding_int)

        return {
            "strategy": "asymmetric",
            "p": self.p,
            "original_l2_norm": np.linalg.norm(embedding),
            "normalized_l2_norm": np.linalg.norm(embedding_norm),
            "quantized_range": (int(embedding_int.min()), int(embedding_int.max())),
            "dequantized_l2_norm": np.linalg.norm(embedding_dequant),
            "quantization_error": float(np.linalg.norm(embedding_norm - embedding_dequant)),
            "max_abs_error": float(np.abs(embedding_norm - embedding_dequant).max()),
            "mean_abs_error": float(np.abs(embedding_norm - embedding_dequant).mean())
        }


class SymmetricQuantizerWithOffset:
    """
    策略2: 对称量化 + 偏移映射

    先进行对称量化到 [-2^(bits-1), 2^(bits-1)-1]
    然后偏移映射到 [0, p-1]

    优点:
    - 保持对称性 (0 在中点)
    - 与传统量化方法兼容
    - 理论基础扎实
    - 可以复用已有的对称量化分析

    缺点:
    - 需要额外的偏移映射步骤
    - 实现稍复杂
    """

    def __init__(self, p: int = 67108859, bits: int = 26):
        """
        初始化对称量化器

        Args:
            p: Pedersen 承诺的质数模数 (默认 67108859)
            bits: 量化位数 (默认 26，刚好覆盖 p)
        """
        self.p = p
        self.bits = bits
        self.name = f"SymmetricQuantizer_{bits}bit"
        self.scale = None  # 将在 fit() 中学习

        # 对称量化范围
        # 为了确保偏移后不超过 p-1，我们需要调整对称范围
        # 策略: 使用较小的对称范围，确保 max + offset <= p-1

        # 方案: 对称范围为 [-(p//2), p//2-1]
        # 这样偏移后范围为 [0, p-1]
        self.int_min = -(p // 2)
        self.int_max = p // 2 - 1 if p % 2 == 1 else p // 2

        # 偏移量：将对称范围映射到 [0, p-1]
        self.offset = p // 2

        # 验证范围
        if self.int_max + self.offset > p - 1:
            raise ValueError(
                f"偏移后超出范围！max={self.int_max} + offset={self.offset} "
                f"= {self.int_max + self.offset} > p-1={p-1}"
            )

        # 验证位数是否足够表示对称范围
        max_symmetric_abs = max(abs(self.int_min), abs(self.int_max))
        bits_needed = max_symmetric_abs.bit_length() + 1  # +1 for sign
        if bits < bits_needed:
            raise ValueError(
                f"位数不足！需要至少 {bits_needed} bits 来表示对称范围 "
                f"[{self.int_min:,}, {self.int_max:,}]"
            )

        print(f"[{self.name}] 初始化完成")
        print(f"  质数 p = {self.p:,}")
        print(f"  量化位数: {self.bits}")
        print(f"  对称范围: [{self.int_min:,}, {self.int_max:,}]")
        print(f"  偏移量: {self.offset:,}")
        print(f"  Pedersen 范围: [0, {self.p - 1:,}]")

    def fit(self, embeddings: np.ndarray) -> 'SymmetricQuantizerWithOffset':
        """
        学习量化参数（缩放因子）

        Args:
            embeddings: 训练样本的特征向量 (N × 512)

        Returns:
            self (支持链式调用)
        """
        # 步骤1: L2归一化
        embeddings_norm = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        # 步骤2: 找到最大绝对值
        max_val = np.abs(embeddings_norm).max()

        # 步骤3: 计算缩放因子
        # 目标: 将 [-max_val, max_val] 映射到 [int_min, int_max]
        # 注意: 我们使用实际的对称范围，而不是 2^(bits-1)-1
        self.scale = self.int_max / max_val

        print(f"[{self.name}] 学习完成")
        print(f"  样本数: {len(embeddings):,}")
        print(f"  最大绝对值: {max_val:.6f}")
        print(f"  缩放因子: {self.scale:.2f}")
        print(f"  实际对称范围: [{self.int_min:,}, {self.int_max:,}]")

        return self

    def quantize(self, embedding: np.ndarray) -> np.ndarray:
        """
        量化单个特征向量

        Args:
            embedding: 浮点特征向量 (512维)

        Returns:
            量化后的整数向量，范围 [0, p-1]
        """
        if self.scale is None:
            raise ValueError("请先调用 fit() 方法学习量化参数！")

        # 步骤1: L2归一化
        embedding_norm = embedding / np.linalg.norm(embedding)

        # 步骤2: 缩放
        embedding_scaled = embedding_norm * self.scale

        # 步骤3: 对称量化（四舍五入）
        embedding_symmetric = np.round(embedding_scaled).astype(np.int32)

        # 步骤4: 裁剪到对称范围
        embedding_symmetric = np.clip(embedding_symmetric, self.int_min, self.int_max)

        # 步骤5: 偏移映射到 Pedersen 域 [0, p-1]
        # 使用模运算确保在有效范围内
        embedding_pedersen = (embedding_symmetric + self.offset) % self.p

        return embedding_pedersen.astype(np.int64)

    def dequantize(self, embedding_int: np.ndarray) -> np.ndarray:
        """
        反量化：整数 → 浮点

        Args:
            embedding_int: 量化后的整数向量 (Pedersen 域)

        Returns:
            反量化后的浮点向量
        """
        if self.scale is None:
            raise ValueError("请先调用 fit() 方法学习量化参数！")

        # 步骤1: 反向偏移映射
        # 从 [0, p-1] 映射回对称范围 [-2^(bits-1), 2^(bits-1)-1]
        embedding_symmetric = ((embedding_int - self.offset + self.p) % self.p).astype(np.int32)

        # 处理符号：将大于 int_max 的值映射到负数
        mask = embedding_symmetric > self.int_max
        embedding_symmetric[mask] = embedding_symmetric[mask] - self.p

        # 步骤2: 反向缩放
        embedding_float = embedding_symmetric.astype(np.float64) / self.scale

        return embedding_float.astype(np.float32)

    def get_quantization_info(self, embedding: np.ndarray, embedding_int: np.ndarray) -> dict:
        """
        获取量化信息用于分析

        Args:
            embedding: 原始浮点向量
            embedding_int: 量化后的整数向量 (Pedersen 域)

        Returns:
            包含量化统计信息的字典
        """
        if self.scale is None:
            raise ValueError("请先调用 fit() 方法学习量化参数！")

        embedding_norm = embedding / np.linalg.norm(embedding)

        # 反向偏移得到对称域的值
        embedding_symmetric = ((embedding_int - self.offset + self.p) % self.p).astype(np.int32)
        mask = embedding_symmetric > self.int_max
        embedding_symmetric[mask] = embedding_symmetric[mask] - self.p

        embedding_dequant = self.dequantize(embedding_int)

        return {
            "strategy": "symmetric_with_offset",
            "p": self.p,
            "bits": self.bits,
            "scale": float(self.scale),
            "original_l2_norm": np.linalg.norm(embedding),
            "normalized_l2_norm": np.linalg.norm(embedding_norm),
            "symmetric_range": (int(embedding_symmetric.min()), int(embedding_symmetric.max())),
            "pedersen_range": (int(embedding_int.min()), int(embedding_int.max())),
            "dequantized_l2_norm": np.linalg.norm(embedding_dequant),
            "quantization_error": float(np.linalg.norm(embedding_norm - embedding_dequant)),
            "max_abs_error": float(np.abs(embedding_norm - embedding_dequant).max()),
            "mean_abs_error": float(np.abs(embedding_norm - embedding_dequant).mean())
        }


def euclidean_distance(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """
    计算欧氏距离 (BioZero 协议使用)

    Args:
        emb1: 第一个向量
        emb2: 第二个向量

    Returns:
        欧氏距离
    """
    return float(np.sqrt(np.sum((emb1 - emb2) ** 2)))


def compare_quantizers(embeddings: np.ndarray,
                       quantizer1: Union[AsymmetricQuantizer, SymmetricQuantizerWithOffset],
                       quantizer2: Union[AsymmetricQuantizer, SymmetricQuantizerWithOffset]) -> dict:
    """
    对比两种量化器的性能

    Args:
        embeddings: 测试样本 (N × 512)
        quantizer1: 第一个量化器
        quantizer2: 第二个量化器

    Returns:
        对比结果字典
    """
    n = len(embeddings)

    # 计算基准距离矩阵
    distances_baseline = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            distances_baseline[i, j] = euclidean_distance(embeddings[i], embeddings[j])

    # 量化器1
    embeddings_int1 = np.array([quantizer1.quantize(emb) for emb in embeddings])
    embeddings_dequant1 = np.array([quantizer1.dequantize(emb_int) for emb_int in embeddings_int1])
    distances_q1 = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            distances_q1[i, j] = euclidean_distance(embeddings_dequant1[i], embeddings_dequant1[j])

    # 量化器2
    embeddings_int2 = np.array([quantizer2.quantize(emb) for emb in embeddings])
    embeddings_dequant2 = np.array([quantizer2.dequantize(emb_int) for emb_int in embeddings_int2])
    distances_q2 = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            distances_q2[i, j] = euclidean_distance(embeddings_dequant2[i], embeddings_dequant2[j])

    # 计算偏差
    deviation1 = np.abs(distances_baseline - distances_q1)
    deviation2 = np.abs(distances_baseline - distances_q2)

    return {
        "quantizer1": {
            "name": quantizer1.name,
            "mean_deviation": float(deviation1.mean()),
            "max_deviation": float(deviation1.max()),
            "relative_deviation_percent": float(deviation1.mean() / distances_baseline[distances_baseline > 0].mean() * 100)
        },
        "quantizer2": {
            "name": quantizer2.name,
            "mean_deviation": float(deviation2.mean()),
            "max_deviation": float(deviation2.max()),
            "relative_deviation_percent": float(deviation2.mean() / distances_baseline[distances_baseline > 0].mean() * 100)
        }
    }


if __name__ == "__main__":
    print("="*70)
    print("Pedersen 量化器测试")
    print("="*70)

    # 测试数据
    np.random.seed(42)
    test_embeddings = np.random.randn(5, 512).astype(np.float32)

    # 归一化
    test_embeddings = test_embeddings / np.linalg.norm(test_embeddings, axis=1, keepdims=True)

    print("\n[测试] 策略1: 非对称量化")
    print("-" * 70)
    q1 = AsymmetricQuantizer(p=67108859)
    emb_int1 = q1.quantize(test_embeddings[0])
    info1 = q1.get_quantization_info(test_embeddings[0], emb_int1)
    print(f"量化误差: {info1['quantization_error']:.8f}")
    print(f"Pedersen 范围: {info1['quantized_range']}")

    print("\n[测试] 策略2: 对称量化 + 偏移映射 (26-bit)")
    print("-" * 70)
    q2 = SymmetricQuantizerWithOffset(p=67108859, bits=26)
    q2.fit(test_embeddings)
    emb_int2 = q2.quantize(test_embeddings[0])
    info2 = q2.get_quantization_info(test_embeddings[0], emb_int2)
    print(f"量化误差: {info2['quantization_error']:.8f}")
    print(f"对称范围: {info2['symmetric_range']}")
    print(f"Pedersen 范围: {info2['pedersen_range']}")

    print("\n[对比] 两种策略")
    print("-" * 70)
    comparison = compare_quantizers(test_embeddings, q1, q2)
    print(f"{comparison['quantizer1']['name']}: 相对偏差 {comparison['quantizer1']['relative_deviation_percent']:.6f}%")
    print(f"{comparison['quantizer2']['name']}: 相对偏差 {comparison['quantizer2']['relative_deviation_percent']:.6f}%")

    print("\n" + "="*70)
    print("测试完成")
    print("="*70)
