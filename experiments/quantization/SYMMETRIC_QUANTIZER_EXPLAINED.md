# 对称量化器 (Symmetric Quantizer) 详解

## 一、什么是量化？

### 基本概念

**量化 (Quantization)** 是将连续的浮点数映射到离散的整数值的过程。

```
浮点数 (32-bit float)  →  量化  →  整数 (8/16-bit int)
  -0.01598074                      -3574
  0.11311719                       25296
```

### 为什么需要量化？

在**BioZero协议**中：
1. **Pedersen承诺只能在整数域上工作** (有限域 Zp)
2. FaceNet输出的是浮点特征向量
3. 需要将浮点→整数，才能使用Pedersen承诺加密

---

## 二、对称量化 vs 非对称量化

### 对称量化 (Symmetric Quantization)

**定义**: 量化范围**关于0对称**，即 `[-max, max] → [-2^(n-1), 2^(n-1)-1]`

**特点**:
- ✅ 零点固定在0
- ✅ 实现简单
- ✅ 适合归一化后的数据
- ⚠️  可能浪费量化范围（如果数据偏向一侧）

**示例** (8-bit对称量化):
```
浮点范围: [-1.0, 1.0]
    ↓
整数范围: [-127, 127]

映射规则:
  -1.0  →  -127
   0.0  →    0
  +1.0  →  +127
```

### 非对称量化 (Asymmetric Quantization)

**定义**: 量化范围可以**不对称**，即 `[min, max] → [0, 2^n-1]` 或 `[min, max] → [-2^(n-1), 2^(n-1)-1]`

**特点**:
- ✅ 更充分利用量化范围
- ✅ 适合偏斜分布的数据
- ⚠️  需要额外存储零点 (zero-point)
- ⚠️  实现更复杂

**示例** (8-bit非对称量化):
```
浮点范围: [0.2, 0.8]
    ↓
整数范围: [0, 255]

映射规则:
  0.2  →    0
  0.5  →  128
  0.8  →  255
```

---

## 三、BioZero使用的对称量化器

### 算法流程

```
输入: 浮点特征向量 f ∈ ℝ^512
输出: 整数特征向量 f_int ∈ ℤ^512

步骤1: L2归一化
  f_norm = f / ||f||₂

步骤2: 计算缩放因子
  max_val = max(|f_norm|)
  scale = (2^(bits-1) - 1) / max_val

步骤3: 缩放
  f_scaled = f_norm × scale

步骤4: 量化 (四舍五入)
  f_int = round(f_scaled)

步骤5: 裁剪到有效范围
  f_int = clip(f_int, -2^(bits-1), 2^(bits-1)-1)
```

### 代码实现

```python
class SymmetricQuantizer:
    def __init__(self, bits=16):
        self.bits = bits        # 量化位数
        self.scale = None       # 缩放因子

    def fit(self, embeddings):
        """学习量化参数（缩放因子）"""
        # L2归一化
        embeddings_norm = embeddings / np.linalg.norm(
            embeddings, axis=1, keepdims=True
        )

        # 找到最大绝对值
        max_val = np.abs(embeddings_norm).max()

        # 计算缩放因子
        # 目标: 将 [-max_val, max_val] 映射到 [-2^(n-1)+1, 2^(n-1)-1]
        self.scale = (2 ** (self.bits - 1) - 1) / max_val
        return self

    def quantize(self, embedding):
        """量化单个向量"""
        # 1. L2归一化
        embedding_norm = embedding / np.linalg.norm(embedding)

        # 2. 缩放
        embedding_scaled = embedding_norm * self.scale

        # 3. 裁剪到有效范围
        int_min = -(2 ** (self.bits - 1))      # 16-bit: -32768
        int_max = 2 ** (self.bits - 1) - 1    # 16-bit: 32767
        embedding_clipped = np.clip(embedding_scaled, int_min, int_max)

        # 4. 四舍五入
        embedding_int = np.round(embedding_clipped).astype(np.int32)

        return embedding_int

    def dequantize(self, embedding_int):
        """反量化：整数 → 浮点"""
        return embedding_int.astype(np.float32) / self.scale
```

---

## 四、具体例子

### 16-bit 对称量化示例

**原始特征向量** (前5维):
```python
embedding = [-0.01598074, -0.01438622, -0.01944660, -0.03140347, 0.11311719]
```

**步骤1: L2归一化**
```python
norm = ||embedding||₂ = 1.0  # FaceNet已经归一化
embedding_norm = embedding / 1.0 = embedding
# [-0.01598074, -0.01438622, -0.01944660, -0.03140347, 0.11311719]
```

**步骤2: 计算缩放因子**
```python
max_val = 0.146527  # 整个数据集的最大绝对值
scale = (2^15 - 1) / 0.146527
scale = 32767 / 0.146527
scale = 223623.96
```

**步骤3: 缩放**
```python
embedding_scaled = embedding_norm × 223623.96
# [-3573.68, -3217.10, -4348.73, -7022.57, 25295.72]
```

**步骤4: 量化 (四舍五入)**
```python
embedding_int = round(embedding_scaled)
# [-3574, -3217, -4349, -7023, 25296]
```

**步骤5: 反量化**
```python
embedding_dequant = embedding_int / 223623.96
# [-0.01598219, -0.01438576, -0.01944783, -0.03140540, 0.11311846]
```

**量化误差**:
```python
error = embedding_norm - embedding_dequant
# [0.00000145, 0.00000046, 0.00000123, 0.00000193, -0.00000127]

euclidean_error = ||error||₂ = 0.00002888
```

---

## 五、为什么选择对称量化？

### BioZero协议的需求

1. **L2归一化特征**
   - FaceNet输出的特征已经L2归一化 (||f||₂ = 1)
   - 数据分布接近对称

2. **计算简单**
   - 零点固定在0，不需要额外存储
   - Pedersen承诺的同态计算更简单

3. **精度足够**
   - 16-bit对称量化误差 < 0.0001%
   - 对认证决策无影响

### 对比其他量化方法

| 特性 | 对称量化 | 非对称量化 | 动态量化 |
|------|---------|-----------|---------|
| **零点** | 固定为0 | 需要存储 | 每次计算 |
| **量化范围利用** | 中等 | 高 | 最高 |
| **计算复杂度** | 低 | 中 | 高 |
| **存储开销** | 最小 | 中 | 中 |
| **适合场景** | 归一化数据 | 偏斜数据 | 动态范围大 |
| **BioZero兼容** | ✅ 优秀 | ⚠️ 复杂 | ❌ 不适合 |

---

## 六、量化参数详解

### 量化位数 (bits)

**定义**: 用多少位来表示量化后的整数

| 位数 | 整数范围 | 精度 | 应用场景 |
|------|---------|------|---------|
| 8-bit | [-127, 127] | 中等 | 边缘设备 |
| 12-bit | [-2047, 2047] | 高 | **推荐** |
| 16-bit | [-32767, 32767] | 极高 | 高精度需求 |
| 32-bit | [-2^31, 2^31-1] | 接近浮点 | 不需要量化 |

**BioZero实验结果**:
```
8-bit:  相对偏差 0.017%,  SNR 42.4 dB  → 可用
12-bit: 相对偏差 0.002%,  SNR 65.7 dB  → 推荐 ⭐⭐⭐
16-bit: 相对偏差 0.0001%, SNR 72.8 dB  → 高精度
```

### 缩放因子 (scale)

**作用**: 将浮点范围映射到整数范围

**计算公式**:
```python
scale = (2^(bits-1) - 1) / max_val
```

**示例** (16-bit):
```python
max_val = 0.146527  # 数据集最大绝对值
scale = 32767 / 0.146527 = 223623.96
```

**物理意义**:
- scale越大 → 精度越高 → 量化误差越小
- scale受限于: 数据范围 和 量化位数

---

## 七、量化误差分析

### 误差来源

1. **舍入误差** (主要)
   - 四舍五入导致
   - 误差范围: ±0.5 × (1/scale)

2. **裁剪误差** (次要)
   - 超出量化范围被裁剪
   - 在BioZero中几乎不发生

### 误差计算

**均方误差 (MSE)**:
```python
MSE = mean((f_original - f_dequant)²)
```

**欧氏距离偏差** (BioZero关键指标):
```python
Euclidean_error = ||f_original - f_dequant||₂
```

**信噪比 (SNR)**:
```python
SNR = 10 × log₁₀(signal_power / noise_power)
```

### 16-bit量化的误差

实验数据:
```
平均欧氏距离偏差: 0.000029
平均MSE: 1.66e-12
平均SNR: 72.84 dB
```

**结论**: 误差极小，对BioZero认证无影响！

---

## 八、与Pedersen承诺的关系

### Pedersen承诺要求

Pedersen承诺定义在有限域 **Zp** (整数模p):
```
c = g^m × h^r (mod p)
```

其中:
- m ∈ Zp: 消息（必须是整数）
- r ∈ Zp: 随机数
- p: 大素数

### 量化的作用

```
FaceNet输出
  ↓ (浮点向量)
对称量化器
  ↓ (整数向量)
Pedersen承诺
  ↓ (承诺)
BioZero协议
```

**关键**: 量化是连接**浮点特征**和**整数域承诺**的桥梁！

---

## 九、总结

### 对称量化器的定义

**对称量化器**是一种将浮点数映射到**关于0对称的整数范围**的量化方法，特别适合**归一化后的数据**。

### 核心特点

1. ✅ **零点固定**: zero-point = 0
2. ✅ **范围对称**: [-2^(n-1), 2^(n-1)-1]
3. ✅ **实现简单**: 只需一个缩放因子
4. ✅ **精度高**: 16-bit偏差 < 0.0001%

### BioZero中的应用

```python
# 1. 初始化量化器
quantizer = SymmetricQuantizer(bits=12)  # 推荐12-bit

# 2. 学习缩放因子
quantizer.fit(all_embeddings)

# 3. 量化
embedding_int = quantizer.quantize(embedding_float)

# 4. 反量化（用于验证）
embedding_recovered = quantizer.dequantize(embedding_int)

# 5. 用于Pedersen承诺
commitment = pedersen_commit(embedding_int)
```

### 性能保证

| 量化位数 | 距离偏差 | 认证影响 |
|---------|---------|---------|
| 8-bit | 0.017% | 无影响 ✅ |
| 12-bit | 0.002% | 无影响 ✅ |
| 16-bit | 0.0001% | 无影响 ✅ |

**结论**: 对称量化完美适配BioZero协议！

---

## 十、扩展阅读

### 相关概念

- **量化感知训练 (QAT)**: 在训练时考虑量化误差
- **后训练量化 (PTQ)**: 训练后直接量化（BioZero使用）
- **混合精度**: 不同层使用不同位数

### 参考文献

1. Jacob et al., "Quantization and Training of Neural Networks", CVPR 2018
2. Pedersen, "Non-Interactive and Information-Theoretic Secure Verifiable Secret Sharing", CRYPTO 1991
3. BioZero论文: "An Efficient and Privacy-Preserving Decentralized Biometric Authentication Protocol"

---

**文档版本**: v1.0
**创建日期**: 2025-10-09
**适用场景**: BioZero量化实验
