# FaceNet MobileNet 模型使用指南

## 模型概述

### 模型信息
- **模型文件**: `biozero_quantization_experiment/models/facenet_mobilenet.pth`
- **模型大小**: 18 MB
- **Backbone**: MobileNetV1
- **Embedding维度**: 128维 (可配置为256维)
- **输入尺寸**: 160x160x3 (RGB)

### 模型架构

```
输入图像 (160x160x3)
    ↓
MobileNetV1 Backbone (特征提取)
    ↓
1024维特征图
    ↓
AdaptiveAvgPool2d (全局平均池化)
    ↓
Flatten (展平)
    ↓
Dropout (防止过拟合)
    ↓
Linear (Bottleneck层: 1024→128或256)
    ↓
BatchNorm1d (归一化)
    ↓
L2 Normalize (输出单位向量)
    ↓
128维或256维特征向量
```

## 使用方法

### 方法1: 使用facenetMRL2_存档的Facenet类 (推荐)

这是最简单的方法,可以直接比对两张人脸:

```python
import sys
sys.path.append('/path/to/facenetMRL2_存档')
from facenet import Facenet
from PIL import Image

# 1. 初始化模型
model = Facenet(
    model_path="biozero_quantization_experiment/models/facenet_mobilenet.pth",
    backbone="mobilenet",           # 使用MobileNet backbone
    input_shape=[160, 160, 3],      # 输入尺寸
    cuda=False                      # 使用CPU (如有GPU设为True)
)

# 2. 加载两张人脸图片
image1 = Image.open("person1_photo1.jpg")
image2 = Image.open("person1_photo2.jpg")

# 3. 计算距离 (欧式距离)
distance = model.detect_image(image1, image2)
print(f"欧式距离: {distance}")

# 4. 判断是否为同一人
threshold = 0.6  # 阈值需要根据验证集调整
is_same_person = distance < threshold
print(f"是否为同一人: {is_same_person}")
```

### 方法2: 提取特征向量 (用于BioZero实验)

如果需要提取特征向量进行量化或其他处理:

```python
import sys
sys.path.append('/path/to/facenetMRL2_存档')
from facenet import Facenet
import torch
import numpy as np
from PIL import Image

# 1. 初始化模型
model = Facenet(
    model_path="biozero_quantization_experiment/models/facenet_mobilenet.pth",
    backbone="mobilenet",
    cuda=False
)

# 2. 图像预处理
def preprocess_image(image_path):
    from utils.utils import resize_image, preprocess_input

    image = Image.open(image_path)
    image = resize_image(image, [160, 160], letterbox_image=True)

    photo = np.array(image, np.float32)
    photo = preprocess_input(photo)  # 归一化: (x - 127.5) / 128.0
    photo = np.transpose(photo, (2, 0, 1))  # HWC -> CHW
    photo = np.expand_dims(photo, 0)  # 增加batch维度

    return torch.from_numpy(photo)

# 3. 提取特征向量
model.net.eval()
with torch.no_grad():
    image1_tensor = preprocess_image("image1.jpg")
    embedding1 = model.net(image1_tensor).cpu().numpy()[0]

    image2_tensor = preprocess_image("image2.jpg")
    embedding2 = model.net(image2_tensor).cpu().numpy()[0]

print(f"特征向量1: {embedding1.shape}")  # (128,)
print(f"特征向量2: {embedding2.shape}")  # (128,)
print(f"L2范数: {np.linalg.norm(embedding1):.4f}")  # 应该接近1.0

# 4. 计算距离
euclidean_dist = np.linalg.norm(embedding1 - embedding2)
cosine_dist = 1 - np.dot(embedding1, embedding2) / (
    np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
)

print(f"欧式距离: {euclidean_dist:.4f}")
print(f"余弦距离: {cosine_dist:.4f}")
```

### 方法3: 结合量化器 (BioZero协议)

用于BioZero实验的完整流程:

```python
import sys
sys.path.append('biozero_quantization_experiment/scripts')
from pedersen_quantizers import AsymmetricQuantizer
import numpy as np

# 1. 提取特征向量 (使用方法2)
embedding1 = ...  # 128维浮点特征向量
embedding2 = ...

# 2. 初始化量化器
quantizer = AsymmetricQuantizer(p=67108859)  # 26-bit质数
print(f"缩放因子: {quantizer.scale_factor:,.0f}")

# 3. 量化特征向量到整数域
embedding1_int = quantizer.quantize(embedding1)
embedding2_int = quantizer.quantize(embedding2)

print(f"量化前: {embedding1[:5]}")
print(f"量化后: {embedding1_int[:5]}")

# 4. 在整数域计算欧式距离
diff = embedding1_int.astype(np.int64) - embedding2_int.astype(np.int64)
distance_int = np.sqrt(np.sum(diff ** 2))

print(f"整数域距离: {distance_int:,.2f}")

# 5. 或者计算余弦距离 (整数域)
emb1_float = embedding1_int.astype(np.float64)
emb2_float = embedding2_int.astype(np.float64)
dot_product = np.dot(emb1_float, emb2_float)
norm1 = np.linalg.norm(emb1_float)
norm2 = np.linalg.norm(emb2_float)
cosine_sim = dot_product / (norm1 * norm2)
cosine_dist_int = 1 - cosine_sim

print(f"整数域余弦距离: {cosine_dist_int:.6f}")

# 6. 阈值判断
# 注意: 整数域的阈值需要根据缩放因子调整
threshold_float = 0.6  # 浮点阈值
threshold_int = threshold_float * quantizer.scale_factor  # 欧式距离
# 或者在整数域重新寻找最优阈值 (余弦距离)

is_same_person = distance_int < threshold_int
print(f"是否为同一人: {is_same_person}")
```

## 关键参数说明

### 1. 模型配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `model_path` | `model_data/facenet_mobilenet.pth` | 模型权重文件路径 |
| `backbone` | `"mobilenet"` | Backbone类型 (`mobilenet` 或 `inception_resnetv1`) |
| `input_shape` | `[160, 160, 3]` | 输入图像尺寸 (height, width, channels) |
| `embedding_size` | `128` | 特征向量维度 (128 或 256) |
| `cuda` | `True` | 是否使用GPU加速 |
| `letterbox_image` | `True` | 是否使用不失真的resize |

### 2. 距离度量

#### 欧式距离 (Euclidean Distance)
- **公式**: `d = sqrt(sum((emb1 - emb2)^2))`
- **范围**: [0, +∞)
- **特点**: 对向量幅度敏感
- **阈值**: 通常 < 0.6 表示同一人

#### 余弦距离 (Cosine Distance)
- **公式**: `d = 1 - cosine_similarity`
- **范围**: [0, 2]
- **特点**: 只关注向量方向,对幅度不敏感
- **阈值**: 通常 < 0.4 表示同一人

### 3. 图像预处理

```python
# 标准预处理流程
def preprocess_image(image_path):
    # 1. 读取图像
    image = Image.open(image_path).convert('RGB')

    # 2. Resize到160x160
    image = image.resize((160, 160))

    # 3. 转numpy数组
    image_array = np.array(image, dtype=np.float32)

    # 4. 归一化: (x - 127.5) / 128.0
    image_array = (image_array - 127.5) / 128.0

    # 5. 转换维度: (H, W, C) -> (C, H, W)
    image_array = np.transpose(image_array, (2, 0, 1))

    # 6. 增加batch维度: (C, H, W) -> (1, C, H, W)
    image_array = np.expand_dims(image_array, 0)

    # 7. 转tensor
    tensor = torch.from_numpy(image_array)

    return tensor
```

## 实验结果参考

基于我们的量化实验结果:

### 余弦距离 + 多位量化性能

| 位数 | 质数 | F1-Score | 性能变化 |
|------|------|----------|---------|
| Float32 (基准) | - | 0.9542 | - |
| 8-bit | 251 | 0.9542 | -0.001% |
| 12-bit | 4,093 | 0.9542 | +0.002% |
| 16-bit | 65,521 | 0.9542 | +0.003% |
| 26-bit | 67,108,859 | 0.9542 | +0.003% |

**结论**: 即使是8-bit量化,使用余弦距离的性能损失几乎为零!

### 推荐配置 (BioZero)

**用于生产环境**:
- **距离度量**: 余弦距离 (对量化更鲁棒)
- **量化位数**: 12-bit或16-bit (质数: 4,093 或 65,521)
- **阈值**: 在验证集上调整,余弦距离约0.0008

**用于实验验证**:
- **距离度量**: 欧式距离或余弦距离
- **量化位数**: 26-bit (质数: 67,108,859)
- **阈值**: 根据实验数据调整

## 性能优化建议

### 1. 批量处理

```python
# 批量提取特征向量
def batch_extract_embeddings(model, image_paths, batch_size=32):
    embeddings = []

    for i in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[i:i+batch_size]
        batch_tensors = [preprocess_image(p) for p in batch_paths]
        batch_tensor = torch.cat(batch_tensors, dim=0)

        with torch.no_grad():
            batch_embeddings = model.net(batch_tensor).cpu().numpy()
            embeddings.extend(batch_embeddings)

    return np.array(embeddings)
```

### 2. GPU加速

```python
# 使用GPU加速
model = Facenet(
    model_path="model.pth",
    cuda=True  # 启用GPU
)
```

### 3. 向量存储

```python
# 使用NumPy存储特征向量
import numpy as np

# 保存
embeddings = np.array([emb1, emb2, emb3, ...])
labels = ['person1', 'person2', 'person3', ...]
np.savez('embeddings.npz', embeddings=embeddings, labels=labels)

# 加载
data = np.load('embeddings.npz')
embeddings = data['embeddings']
labels = data['labels']
```

### 4. 快速检索

```python
# 使用FAISS进行快速检索 (可选)
import faiss

# 构建索引
index = faiss.IndexFlatL2(128)  # 128维向量
index.add(embeddings)

# 搜索最近邻
query_embedding = np.array([embedding1])
distances, indices = index.search(query_embedding, k=5)  # 返回最近的5个

print(f"最近的5个人: {labels[indices[0]]}")
print(f"距离: {distances[0]}")
```

## 常见问题

### Q1: 如何确定最优阈值?

A: 在验证集上评估不同阈值的性能,选择F1-Score最高的阈值:

```python
from sklearn.metrics import f1_score

thresholds = np.linspace(0.3, 1.0, 100)
best_f1 = 0
best_threshold = 0

for threshold in thresholds:
    predictions = (distances < threshold).astype(int)
    f1 = f1_score(true_labels, predictions)

    if f1 > best_f1:
        best_f1 = f1
        best_threshold = threshold

print(f"最优阈值: {best_threshold:.4f}, F1: {best_f1:.4f}")
```

### Q2: 欧式距离还是余弦距离?

A:
- **欧式距离**: 更直观,对向量幅度敏感
- **余弦距离**: 对量化更鲁棒,只关注方向

根据我们的实验,**余弦距离**在量化场景下表现更好。

### Q3: 如何处理低质量图片?

A:
1. 使用MTCNN进行人脸检测和对齐
2. 确保人脸清晰可见,占图像比例合适
3. 图像质量评估,过滤低质量样本

### Q4: 模型可以fine-tune吗?

A: 可以,但需要注意:
1. 保持输入尺寸160x160
2. 保持embedding维度不变
3. 使用triplet loss或其他度量学习损失

## 参考资源

- **原始项目**: [facenetMRL2_存档](../facenetMRL2_存档/)
- **量化实验脚本**: `biozero_quantization_experiment/scripts/`
- **实验报告**: `biozero_quantization_experiment/outputs/`
- **测试脚本**: `test_facenet_mobilenet_model.py`

## 联系方式

如有问题,请查看项目文档或联系开发团队。
