# Pedersen 量化策略对比实验报告

## 📊 实验概述

**实验日期**: 2025-10-10
**实验目的**: 对比两种Pedersen兼容量化策略的性能
**测试数据**: 5个真实人脸特征向量 (FaceNet/InceptionResnetV1)
**距离度量**: 欧氏距离 (BioZero协议标准)

---

## 🎯 测试策略

### 策略1: 非对称量化 (AsymmetricQuantizer)

**原理**: 直接将 [-1, 1] 映射到 [0, p-1]

```python
映射公式: x_int = (x_float - min) / (max - min) * (p - 1)

浮点范围: [-1.0, 1.0]
整数范围: [0, 67,108,858]
缩放因子: 33,554,429.00
```

**特点**:
- ✅ 直接映射，无需额外转换
- ✅ 充分利用Pedersen域 [0, p-1]
- ✅ 与DeepFace实现一致
- ⚠️ 打破对称性 (0不在中点)

### 策略2: 对称量化 + 偏移映射 (SymmetricQuantizerWithOffset)

**原理**: 先对称量化到 [-p//2, p//2-1]，再偏移到 [0, p-1]

```python
对称范围: [-(p//2), (p//2)-1] = [-33,554,429, 33,554,428]
偏移量: p//2 = 33,554,429
Pedersen范围: [0, p-1] = [0, 67,108,858]

量化公式: x_sym = round(x_norm * scale)
偏移映射: x_ped = (x_sym + offset) mod p
```

**特点**:
- ✅ 保持对称性 (0在中点)
- ✅ 与传统量化理论一致
- ✅ 可扩展到不同位数
- ⚠️ 需要额外的偏移步骤

---

## 📈 实验结果

### 完整对比表

| 量化器 | 策略 | 位数 | 相对偏差 | SNR (dB) | Pedersen范围 |
|--------|------|------|---------|----------|-------------|
| AsymmetricQuantizer | 非对称 | N/A | **0.000009%** | 72.91 | [28,637,790, 37,940,072] |
| SymmetricQuantizer_26bit | 对称+偏移 | 26 | **0.000002%** | 72.91 | [1, 63,484,995] |
| SymmetricQuantizer_28bit | 对称+偏移 | 28 | **0.000002%** | 72.91 | [1, 63,484,995] |
| SymmetricQuantizer_30bit | 对称+偏移 | 30 | **0.000002%** | 72.91 | [1, 63,484,995] |
| SymmetricQuantizer_32bit | 对称+偏移 | 32 | **0.000002%** | 72.91 | [1, 63,484,995] |

### 关键发现

1. **精度相当**: 两种策略的SNR都是 **72.91 dB**
2. **误差极小**: 相对偏差都 < **0.00001%**
3. **对称策略略优**: 相对偏差 **0.000002%** vs **0.000009%**
4. **位数无关**: 26/28/30/32-bit 对称量化结果**完全相同**

---

## 🔬 详细分析

### 为什么 26/28/30/32-bit 结果相同？

**原因**: 实际的对称范围由 p (而非 bits) 决定

```python
# 所有位数的实际对称范围都是:
symmetric_range = [-(p//2), (p//2)-1]
                = [-33,554,429, 33,554,428]

# 这个范围需要 26 bits 来表示
# 因此 28/30/32-bit 都有足够的表示能力
# 但它们的实际使用范围是相同的！

# 缩放因子计算:
scale = int_max / max_val
      = 33,554,428 / 0.146527  # 对所有位数都相同
      = 228,997,899.10
```

**结论**: 对于 p = 67,108,859，**26-bit 是最优选择**，更高位数没有额外收益。

### 距离保真度分析

#### 基准距离矩阵

```
        ID0       ID1       ID2       ID3       ID4
ID0   0.0000   1.4099   0.9415   1.4007   1.4065
ID1   1.4099   0.0000   1.3044   1.0150   1.0758
ID2   0.9415   1.3044   0.0000   1.3486   1.3660
ID3   1.4007   1.0150   1.3486   0.0000   1.1015
ID4   1.4065   1.0758   1.3660   1.1015   0.0000
```

#### 量化后偏差 (策略2, 26-bit)

```
最大偏差: 0.00000012
平均偏差: 0.00000003
```

**解释**: 量化误差在 **纳米级别** (10^-7)，对BioZero认证决策**完全无影响**！

---

## 🏆 推荐方案

### 最优选择: **SymmetricQuantizer_26bit**

**理由**:
1. ✅ **最小位数**: 26-bit 刚好覆盖 Pedersen 域
2. ✅ **最高精度**: 相对偏差仅 0.000002%
3. ✅ **理论优雅**: 对称结构，易于理解和分析
4. ✅ **兼容性好**: 与FaceNet的L2归一化天然配合
5. ✅ **可扩展**: 同一框架可用于不同的质数 p

### 实现建议

```python
from pedersen_quantizers import SymmetricQuantizerWithOffset

# 初始化
quantizer = SymmetricQuantizerWithOffset(p=67108859, bits=26)

# 在训练集上学习缩放因子
quantizer.fit(training_embeddings)

# 量化
embedding_int = quantizer.quantize(embedding_float)

# 用于Pedersen承诺
pedersen = Pedersen(g=56544564, h=237684576)
commitment = pedersen.Commitment(embedding_int[i], random_blinding_factor)
```

---

## 📊 性能对比总结

### 两种策略的优劣

| 维度 | 非对称量化 | 对称量化 + 偏移 | 胜出 |
|------|----------|---------------|------|
| **精度** | 0.000009% | **0.000002%** | ✅ 对称 |
| **SNR** | 72.91 dB | **72.91 dB** | ⚖️ 平手 |
| **实现复杂度** | **简单** | 中等 | ✅ 非对称 |
| **理论基础** | 实用 | **扎实** | ✅ 对称 |
| **可扩展性** | 固定p | **通用** | ✅ 对称 |
| **与DeepFace一致** | **是** | 否 | ✅ 非对称 |
| **与FaceNet理论一致** | 否 | **是** | ✅ 对称 |

### 使用场景建议

**使用非对称量化 (策略1)** 如果:
- 需要与DeepFace实现保持一致
- 追求最简单的实现
- 只针对固定的 p = 67108859

**使用对称量化 (策略2)** 如果:
- 需要最高精度
- 希望理论上更严谨
- 可能需要支持不同的质数 p
- 需要与传统量化研究对接
- **论文发表需要** ⭐

---

## 🔍 深入洞察

### 洞察1: 对称范围的实际约束

传统的对称量化使用 `[-2^(n-1), 2^(n-1)-1]`，但在Pedersen域中：

```python
# 传统26-bit对称范围
traditional_range = [-33554432, 33554431]

# Pedersen兼容的26-bit对称范围
pedersen_range = [-33554429, 33554428]  # 受限于 p

# 区别
# 传统: 范围更大，但偏移后会超出 [0, p-1]
# Pedersen: 范围受 p 约束，偏移后刚好填满 [0, p-1]
```

**启示**: Pedersen量化需要特别的范围设计，不能直接套用传统量化公式。

### 洞察2: 为什么选择 p = 67108859？

```python
p = 67108859 = 2^26 - 5

# 巧妙之处:
# 1. 接近2的幂次 → 硬件友好
# 2. 26-bit刚好 → 无浪费
# 3. 质数 → Pedersen承诺安全性
# 4. 奇数 → 对称范围平衡
```

### 洞察3: SNR的理论上限

```python
理论SNR (n-bit均匀量化) = 6.02n + 1.76 dB

26-bit理论SNR = 6.02 × 26 + 1.76 = 158.28 dB

实际SNR = 72.91 dB

差距原因:
1. 信号未达到量化范围上限
2. L2归一化限制了信号幅度
3. 实际信号功率 < 满量程功率
```

---

## 💡 论文撰写建议

### 实验章节

```latex
\subsection{Quantization for Pedersen Compatibility}

To map FaceNet's float32 embeddings to Pedersen's integer domain
[0, p-1], we propose a symmetric quantization with modular offset:

\begin{equation}
f_{int} = \left( \lfloor f_{norm} \cdot s \rceil + \frac{p}{2} \right) \bmod p
\end{equation}

where $f_{norm}$ is the L2-normalized embedding, $s$ is the scale factor,
and $p = 67,108,859$ is the Pedersen prime.

\textbf{Experimental Results:}
Using 26-bit symmetric quantization on FaceNet embeddings,
we achieve:
\begin{itemize}
  \item Relative distance deviation: 0.000002\%
  \item Signal-to-Noise Ratio: 72.91 dB
  \item Perfect Pedersen compatibility: all values in [0, p-1]
\end{itemize}

This demonstrates that quantization has \textbf{negligible impact}
on BioZero's authentication accuracy.
```

### 关键论点

1. **量化必要性**: Pedersen承诺要求整数域
2. **26-bit充分性**: 相对偏差 < 0.00001%
3. **方法优雅性**: 对称结构，理论扎实
4. **实用价值**: 与FaceNet无缝集成

---

## 📁 生成的文件

```
biozero_quantization_experiment/
├── scripts/
│   ├── pedersen_quantizers.py          # 两种量化器实现
│   └── run_pedersen_comparison.py      # 对比实验脚本
├── outputs/
│   └── results/
│       └── pedersen_comparison_results.json  # 实验结果
└── PEDERSEN_QUANTIZATION_COMPARISON_REPORT.md  # 本报告
```

---

## ✅ 结论

1. **两种策略都优秀**: 相对偏差 < 0.00001%，SNR > 72 dB
2. **对称策略略优**: 精度提升 4.5倍 (0.000002% vs 0.000009%)
3. **26-bit是最优**: 更高位数无额外收益
4. **BioZero兼容性**: 完美适配，对认证决策无影响

## 🎯 推荐

**论文发表**: 使用 **SymmetricQuantizer_26bit**
**实际部署**: 两种策略均可，根据工程需求选择

---

**报告版本**: v1.0
**生成日期**: 2025-10-10
**实验数据**: pedersen_comparison_results.json
**状态**: ✅ 实验完成，推荐已确定
