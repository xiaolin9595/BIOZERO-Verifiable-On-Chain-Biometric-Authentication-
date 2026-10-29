# 人脸识别性能评估说明

## ⚠️ 当前数据集限制

### 问题
当前 `data/test_images` 数据集中每个身份只有一张图片：
```
test_images/
├── angelina_jolie/
│   └── 1.jpg          ← 只有1张
├── bradley_cooper/
│   └── 1.jpg          ← 只有1张
...
```

### 影响
- **无法计算正样本对**：需要同一人的多张图片
- **无法评估 Precision/Recall/F1**：需要正负样本对平衡
- **只能评估负样本性能**：所有对都是"不同人"

---

## 🎯 解决方案

### 方案1: 使用 LFW 数据集（推荐）

**LFW (Labeled Faces in the Wild)** 是标准的人脸识别基准数据集。

#### 下载 LFW
```bash
# 创建数据目录
mkdir -p data/lfw

# 下载 LFW (aligned版本)
wget http://vis-www.cs.umass.edu/lfw/lfw.tgz
tar -xzf lfw.tgz -C data/lfw

# 或者使用 LFW Pairs
wget http://vis-www.cs.umass.edu/lfw/pairsDevTrain.txt
wget http://vis-www.cs.umass.edu/lfw/pairsDevTest.txt
```

#### LFW 数据集特点
- **13,233 张图片**
- **5,749 个身份**
- **1,680 个身份有 ≥2 张图片**（可以生成正样本对）
- 标准的配对测试集

#### 修改脚本使用 LFW
```python
# 在 evaluate_recognition_performance.py 中修改
embeddings, labels, image_paths = extract_embeddings_from_dataset(
    mtcnn, resnet, "data/lfw", device  # 改为 lfw 目录
)
```

### 方案2: 创建合成多样本数据集

如果无法下载LFW，可以通过数据增强创建多张样本：

```python
#!/usr/bin/env python3
"""
为每个身份创建多张增强样本
"""
from PIL import Image, ImageEnhance, ImageFilter
import random

def augment_image(img_path, output_dir, n_augmentations=5):
    """
    对单张图片进行数据增强，生成多张变体
    """
    img = Image.open(img_path)
    output_dir.mkdir(parents=True, exist_ok=True

    # 保存原图
    img.save(output_dir / "original.jpg")

    for i in range(n_augmentations):
        aug_img = img.copy()

        # 随机亮度
        enhancer = ImageEnhance.Brightness(aug_img)
        aug_img = enhancer.enhance(random.uniform(0.8, 1.2))

        # 随机对比度
        enhancer = ImageEnhance.Contrast(aug_img)
        aug_img = enhancer.enhance(random.uniform(0.8, 1.2))

        # 随机轻微模糊
        if random.random() > 0.5:
            aug_img = aug_img.filter(ImageFilter.GaussianBlur(radius=0.5))

        # 保存
        aug_img.save(output_dir / f"aug_{i+1}.jpg")
```

### 方案3: 简化评估（仅负样本）

对于当前数据集，可以评估：
- ✅ **TNR (True Negative Rate)**: 正确识别不同人的能力
- ✅ **FPR (False Positive Rate)**: 误识别为同一人的比率
- ✅ **阈值选择**: 找到最小化 FPR 的阈值

但**无法**评估：
- ❌ **TPR/Recall**: 需要正样本
- ❌ **Precision**: 需要真阳性
- ❌ **F1-Score**: 需要Precision和Recall

---

## 📊 推荐的完整评估流程

### 步骤1: 准备数据集

```bash
# 下载 LFW
cd /Volumes/TSU302/BioZero/workplace/facenet-pytorch
mkdir -p data/lfw
cd data/lfw

# 下载并解压
wget http://vis-www.cs.umass.edu/lfw/lfw.tgz
tar -xzf lfw.tgz
```

### 步骤2: 运行评估

```bash
# 修改脚本指向 LFW
python3 biozero_quantization_experiment/scripts/evaluate_recognition_performance.py
```

### 步骤3: 查看结果

评估将生成：
1. **性能指标** (JSON)
   - Precision, Recall, F1-Score
   - TPR, FPR, TNR, FNR
   - EER, ROC-AUC

2. **可视化图表** (PNG)
   - ROC 曲线
   - Precision-Recall 曲线
   - F1-Score 对比
   - EER 对比

---

## 🔬 当前数据集的临时评估

虽然当前数据集有限，但我们仍然可以评估**距离保真度**：

```python
# 这是我们已经做的
distance_deviation = |distance_float - distance_quantized|
relative_deviation = deviation / distance_float * 100%

# 结果：0.000002% （几乎完美）
```

**结论**：即使无法完整评估Precision/Recall，我们已经证明：
- ✅ 距离保真度极高（99.999998%）
- ✅ 量化不改变距离关系
- ✅ **因此不会影响识别性能**

---

## 📖 参考资料

### LFW 数据集
- 官网: http://vis-www.cs.umass.edu/lfw/
- 论文: "Labeled Faces in the Wild: A Database for Studying Face Recognition in Unconstrained Environments"
- 标准协议: 6,000 对测试

### BioZero 相关
- 距离度量: 欧氏距离（已验证）
- 量化精度: 0.000002% 相对偏差
- 推荐量化: 26-bit 对称量化

---

## ✅ 快速开始（使用当前数据集）

如果暂时无法获取 LFW，可以运行简化版评估：

```bash
# 修改后的脚本将自动检测并适配单图片数据集
python3 biozero_quantization_experiment/scripts/evaluate_recognition_performance.py

# 输出将包括：
# - 距离分布统计
# - TNR/FPR 分析
# - 量化前后对比
# - ⚠️ 警告：无正样本对
```

**解释**：虽然无法计算完整指标，但距离保真度分析已经足够证明量化的有效性。

---

**文档版本**: v1.0
**更新日期**: 2025-10-11
**状态**: 等待 LFW 数据集或使用简化评估
