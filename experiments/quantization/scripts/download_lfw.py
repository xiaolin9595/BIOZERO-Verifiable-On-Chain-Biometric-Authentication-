#!/usr/bin/env python3
"""
下载 LFW 数据集并准备用于评估

使用 Kaggle API 下载 jessicali9530/lfw-dataset
"""

import os
import sys
from pathlib import Path
import json
import shutil

def setup_kaggle_credentials():
    """设置 Kaggle API 凭证"""
    kaggle_dir = Path.home() / '.kaggle'
    kaggle_dir.mkdir(exist_ok=True)

    kaggle_json = kaggle_dir / 'kaggle.json'

    credentials = {
        "username": "lin22563434",
        "key": "405c87fde54f4cb661a5f4bb3840fbfe"
    }

    with open(kaggle_json, 'w') as f:
        json.dump(credentials, f)

    # 设置权限 (仅所有者可读写)
    os.chmod(kaggle_json, 0o600)

    print(f"✓ Kaggle 凭证已保存到: {kaggle_json}")


def download_lfw_dataset():
    """使用 kagglehub 下载 LFW 数据集"""
    print("\n[1] 安装 kagglehub...")
    os.system("pip3 install -q kagglehub")

    print("\n[2] 下载 LFW 数据集...")
    print("    来源: kaggle.com/datasets/jessicali9530/lfw-dataset")
    print("    这可能需要几分钟...")

    try:
        import kagglehub

        # 下载数据集
        path = kagglehub.dataset_download("jessicali9530/lfw-dataset")

        print(f"\n✓ 数据集下载完成！")
        print(f"  路径: {path}")

        return path

    except Exception as e:
        print(f"\n✗ 下载失败: {e}")
        print("\n备选方案：手动下载")
        print("1. 访问: https://www.kaggle.com/datasets/jessicali9530/lfw-dataset")
        print("2. 点击 'Download' 下载 ZIP 文件")
        print("3. 解压到: data/lfw/")
        return None


def organize_lfw_data(download_path):
    """整理 LFW 数据集结构"""
    print("\n[3] 整理数据集结构...")

    # 目标目录
    target_dir = Path("data/lfw")
    target_dir.mkdir(parents=True, exist_ok=True)

    download_path = Path(download_path)

    # 查找 lfw-deepfunneled 目录 (通常是这个名字)
    possible_dirs = [
        download_path / "lfw-deepfunneled",
        download_path / "lfw",
        download_path / "lfw_funneled",
    ]

    source_dir = None
    for dir_path in possible_dirs:
        if dir_path.exists():
            source_dir = dir_path
            break

    if source_dir is None:
        # 如果找不到，列出所有子目录
        print(f"\n  下载目录内容:")
        for item in download_path.iterdir():
            print(f"    - {item.name}")

        # 使用第一个子目录
        subdirs = [d for d in download_path.iterdir() if d.is_dir()]
        if subdirs:
            source_dir = subdirs[0]
            print(f"\n  使用目录: {source_dir.name}")

    if source_dir:
        # 复制或创建符号链接
        print(f"  源目录: {source_dir}")
        print(f"  目标目录: {target_dir}")

        if (target_dir / "lfw").exists():
            print("  目标已存在，跳过")
        else:
            # 创建符号链接（更快）
            try:
                os.symlink(source_dir, target_dir / "lfw", target_is_directory=True)
                print("  ✓ 创建符号链接")
            except:
                # 如果符号链接失败，复制目录（较慢）
                print("  符号链接失败，正在复制文件...")
                shutil.copytree(source_dir, target_dir / "lfw")
                print("  ✓ 文件复制完成")

        return target_dir / "lfw"
    else:
        print("\n✗ 无法找到 LFW 数据")
        return None


def analyze_lfw_structure(lfw_dir):
    """分析 LFW 数据集结构"""
    print("\n[4] 分析数据集...")

    if not lfw_dir or not lfw_dir.exists():
        print("✗ 目录不存在")
        return

    # 统计身份和图片数量
    identities = []
    images_per_identity = {}

    for person_dir in lfw_dir.iterdir():
        if person_dir.is_dir() and not person_dir.name.startswith('.'):
            identity = person_dir.name
            images = list(person_dir.glob("*.jpg"))

            if images:
                identities.append(identity)
                images_per_identity[identity] = len(images)

    total_images = sum(images_per_identity.values())
    multi_image_identities = {k: v for k, v in images_per_identity.items() if v >= 2}

    print(f"\n  总身份数: {len(identities)}")
    print(f"  总图片数: {total_images}")
    print(f"  有 ≥2 张图片的身份: {len(multi_image_identities)}")
    print(f"  平均每个身份的图片数: {total_images / len(identities):.2f}")

    # 显示一些统计
    image_counts = list(images_per_identity.values())
    print(f"\n  图片数分布:")
    print(f"    最少: {min(image_counts)} 张")
    print(f"    最多: {max(image_counts)} 张")
    print(f"    中位数: {sorted(image_counts)[len(image_counts)//2]} 张")

    # 显示有多张图片的身份示例
    print(f"\n  多图片身份示例 (前5个):")
    for i, (identity, count) in enumerate(sorted(multi_image_identities.items(),
                                                  key=lambda x: -x[1])[:5]):
        print(f"    {i+1}. {identity}: {count} 张")

    return len(identities), total_images, len(multi_image_identities)


def main():
    print("="*70)
    print("LFW 数据集下载与准备")
    print("="*70)

    # 设置 Kaggle 凭证
    setup_kaggle_credentials()

    # 下载数据集
    download_path = download_lfw_dataset()

    if download_path:
        # 整理数据
        lfw_dir = organize_lfw_data(download_path)

        if lfw_dir:
            # 分析数据集
            num_identities, num_images, num_multi = analyze_lfw_structure(lfw_dir)

            print("\n" + "="*70)
            print("✓ LFW 数据集准备完成！")
            print("="*70)
            print(f"\n数据集路径: {lfw_dir}")
            print(f"\n可用于评估:")
            print(f"  - {num_multi} 个身份可以生成正样本对")
            print(f"  - {num_identities} 个身份总计")
            print(f"  - {num_images} 张图片")

            print(f"\n下一步：运行评估")
            print(f"  python3 biozero_quantization_experiment/scripts/evaluate_recognition_performance.py")
            print(f"  (记得修改脚本中的数据集路径为: data/lfw/lfw)")

        else:
            print("\n✗ 数据集准备失败")
    else:
        print("\n✗ 数据集下载失败")
        print("\n请尝试手动下载:")
        print("  1. 访问: https://www.kaggle.com/datasets/jessicali9530/lfw-dataset")
        print("  2. 下载并解压到: data/lfw/")


if __name__ == "__main__":
    main()
