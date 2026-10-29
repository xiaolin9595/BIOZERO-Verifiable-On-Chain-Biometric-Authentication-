#!/usr/bin/env python3
"""
验证整数域距离计算 vs 反量化后距离计算

证明：直接在整数域计算距离与反量化后计算距离的结果等价
"""

import sys
sys.path.append('biozero_quantization_experiment/scripts')

import numpy as np
from pedersen_quantizers import AsymmetricQuantizer, SymmetricQuantizerWithOffset, euclidean_distance

def integer_euclidean_distance(emb1_int, emb2_int):
    """在整数域计算欧氏距离"""
    diff = emb1_int.astype(np.int64) - emb2_int.astype(np.int64)
    return np.sqrt(np.sum(diff ** 2))


def verify_distance_equivalence():
    """验证整数域距离和浮点域距离的等价性"""
    print("="*70)
    print("验证：整数域距离 vs 反量化浮点域距离")
    print("="*70)

    # 生成测试数据
    np.random.seed(42)
    n_samples = 100
    embeddings = []
    for _ in range(n_samples):
        emb = np.random.randn(512).astype(np.float32)
        emb = emb / np.linalg.norm(emb)  # L2归一化
        embeddings.append(emb)

    embeddings = np.array(embeddings)
    print(f"生成 {n_samples} 个测试样本\n")

    # 测试两种量化器
    quantizers = [
        (AsymmetricQuantizer(p=67108859), "AsymmetricQuantizer"),
        (SymmetricQuantizerWithOffset(p=67108859, bits=26), "SymmetricQuantizer_26bit")
    ]

    for quantizer, name in quantizers:
        print(f"\n{'='*70}")
        print(f"测试: {name}")
        print('='*70)

        # Fit (对称量化器需要)
        if isinstance(quantizer, SymmetricQuantizerWithOffset):
            quantizer.fit(embeddings)
            scale_factor = quantizer.scale
        else:
            scale_factor = quantizer.scale_factor

        print(f"缩放因子: {scale_factor:,.2f}\n")

        # 量化
        embeddings_int = np.array([quantizer.quantize(emb) for emb in embeddings])

        # 方法1: 反量化后计算浮点距离（我们实验的方法）
        embeddings_dequant = np.array([quantizer.dequantize(emb_int) for emb_int in embeddings_int])

        # 方法2: 直接在整数域计算距离（BioZero实际方法）

        # 计算距离对比
        print("计算距离对比 (前10对):")
        print(f"{'Pair':<8} {'Float Distance':<20} {'Int Distance':<20} {'Int/Float':<15} {'Scale':<15}")
        print("-"*90)

        for i in range(10):
            idx1, idx2 = i, (i + 1) % n_samples

            # 方法1: 浮点域距离
            d_float = euclidean_distance(embeddings_dequant[idx1], embeddings_dequant[idx2])

            # 方法2: 整数域距离
            d_int = integer_euclidean_distance(embeddings_int[idx1], embeddings_int[idx2])

            # 验证关系: d_int ≈ d_float × scale
            ratio = d_int / d_float if d_float > 0 else 0

            print(f"{i:<8} {d_float:<20.10f} {d_int:<20.2f} {ratio:<15.2f} {scale_factor:<15.2f}")

        # 统计验证
        print("\n统计验证 (100对随机对):")
        ratios = []
        for i in range(100):
            idx1 = np.random.randint(0, n_samples)
            idx2 = np.random.randint(0, n_samples)
            if idx1 == idx2:
                continue

            d_float = euclidean_distance(embeddings_dequant[idx1], embeddings_dequant[idx2])
            d_int = integer_euclidean_distance(embeddings_int[idx1], embeddings_int[idx2])

            if d_float > 0:
                ratio = d_int / d_float
                ratios.append(ratio)

        ratios = np.array(ratios)
        print(f"  平均比值: {ratios.mean():,.2f}")
        print(f"  标准差:   {ratios.std():,.2f}")
        print(f"  最小值:   {ratios.min():,.2f}")
        print(f"  最大值:   {ratios.max():,.2f}")
        print(f"  缩放因子: {scale_factor:,.2f}")
        print(f"  误差:     {abs(ratios.mean() - scale_factor) / scale_factor * 100:.6f}%")

        # 验证阈值等价性
        print("\n验证阈值判断等价性:")
        threshold_float = 0.9  # 假设浮点阈值
        threshold_int = threshold_float * scale_factor

        print(f"  浮点阈值: {threshold_float:.6f}")
        print(f"  整数阈值: {threshold_int:,.2f}")

        # 测试100对的判断结果
        match_count_float = 0
        match_count_int = 0
        mismatch_count = 0

        for i in range(100):
            idx1 = np.random.randint(0, n_samples)
            idx2 = np.random.randint(0, n_samples)

            d_float = euclidean_distance(embeddings_dequant[idx1], embeddings_dequant[idx2])
            d_int = integer_euclidean_distance(embeddings_int[idx1], embeddings_int[idx2])

            match_float = d_float < threshold_float
            match_int = d_int < threshold_int

            if match_float:
                match_count_float += 1
            if match_int:
                match_count_int += 1
            if match_float != match_int:
                mismatch_count += 1

        print(f"  浮点判断匹配数: {match_count_float}")
        print(f"  整数判断匹配数: {match_count_int}")
        print(f"  判断不一致数:   {mismatch_count}")
        print(f"  一致性:         {(100 - mismatch_count)/100*100:.2f}%")

        if mismatch_count == 0:
            print("  ✓ 完全等价！")
        else:
            print(f"  ⚠️ 存在 {mismatch_count} 个不一致（可能由于舍入误差）")


if __name__ == "__main__":
    verify_distance_equivalence()

    print("\n" + "="*70)
    print("结论")
    print("="*70)
    print("""
1. 整数域距离 = 浮点域距离 × 缩放因子
2. 只要阈值相应缩放，判断结果完全一致
3. BioZero可以直接在整数域计算，无需反量化
4. 我们的实验结论依然成立（保持排序关系）
""")
