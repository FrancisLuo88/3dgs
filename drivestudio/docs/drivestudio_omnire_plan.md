# DriveStudio OmniRe 训练计划

> 存档日期：2026-02-27  
> 基于：v13 splatfacto 分析结果 + DriveStudio 安装完成后的现状诊断

## 当前状态诊断

安装脚本已经跑完，逐步检查结果：

**已就绪：**

- DriveStudio 代码库：`/home/luosx/3dgs/drivestudio/` ✓
- conda 环境：`drivestudio` 和 `segformer` 均已创建 ✓
- 10 个 mini 场景预处理完毕（000-009 全部存在）✓
- 场景 000（scene-0061）数据：1146 张图片 × 6 摄像头 = 191 帧，191 帧 LiDAR，extrinsics/intrinsics，dynamic_masks ✓

**存在的问题：**

**问题 1：数据路径偏移（双重 mini + _10Hz 后缀）**

setup script 中传入了 `--target_dir processed_10Hz/mini`，但 DriveStudio 的 `preprocess.py` 会**自动追加 `_10Hz` 后缀和 split 名**，导致数据实际落在：

```
data/drivestudio_nuscenes/processed_10Hz_10Hz/mini/mini/000/   ← 实际位置
```

根据 `driving_dataset.py` 第 51 行，`data_path = os.path.join(data_root, f"{scene_idx:03d}")`，所以正确的 data_root 应该是：

```
$WORKSPACE/data/drivestudio_nuscenes/processed_10Hz_10Hz/mini/mini
```

**问题 2：sky_masks 为空（必须项）**

sky_masks 目录存在但 0 个文件。setup script 中的 `extract_masks.py` 指向了旧的（错误的）路径 `processed_10Hz/mini`，所以当时找不到图片，什么都没生成。sky_masks 是 OmniRe 训练的**必须输入**（config 中 `load_sky_mask: True`），必须先提取。

**问题 3：humanpose 数据缺失（可选）**

SMPL 人体姿态数据未下载。OmniRe 用 SMPL-Gaussians 建模行人，没有这个数据时会退化为 DeformableGaussians。

---

## 执行步骤

### Step 1：修复 `run_train_omnire.sh` 的数据路径 ✓

修改 `NUSCENES_PROCESSED` 变量，指向实际数据位置：

```bash
NUSCENES_PROCESSED=$WORKSPACE/data/drivestudio_nuscenes/processed_10Hz_10Hz/mini/mini
```

**逻辑：** DriveStudio 的 `driving_dataset.py` 拼接路径时用 `os.path.join(data_root, "000")`，所以 data_root 必须指向直接包含场景目录的父目录。

### Step 2：提取 sky masks（在 WSL 终端运行）

```bash
conda activate segformer
export PYTHONPATH=/home/luosx/3dgs/drivestudio

python /home/luosx/3dgs/drivestudio/datasets/tools/extract_masks.py \
    --data_root /home/luosx/3dgs/data/drivestudio_nuscenes/processed_10Hz_10Hz/mini/mini \
    --segformer_path /tmp/SegFormer \
    --checkpoint /tmp/SegFormer/pretrained/segformer.b5.1024x1024.city.160k.pth \
    --start_idx 0 \
    --num_scenes 10 \
    --process_dynamic_mask
```

**逻辑：** sky masks 告诉 OmniRe 哪些像素是天空，天空不应该被 Gaussian 拟合（否则天空的"无穷远"会产生巨大 Gaussian 污染整个场景）。这正是后视摄像头噪点的关键原因之一，也是 OmniRe 相比 splatfacto 的核心改进之一。每个场景预计处理 1-3 分钟，10 个场景共约 15-30 分钟。

### Step 3（可选）：下载 SMPL 人体姿态数据

```bash
cd /home/luosx/3dgs/data/drivestudio_nuscenes
gdown 1Z0gJVRtPnjvusQVaW7ghZnwfycZStCZx
unzip nuscenes_preprocess_humanpose.zip
rm nuscenes_preprocess_humanpose.zip
```

解压后，每个场景目录下应出现 `humanpose/smpl.pkl`。注意：解压出来的路径结构需要确认与 `processed_10Hz_10Hz/mini/mini/` 对应。

**逻辑：** 有了 SMPL 数据，行人会被 SMPL-Gaussian 建模（可形变的人体网格+Gaussian），而不是一团模糊。场景 0061 中行人较少，这一步可以先跳过，以后补上。

### Step 4：启动 OmniRe 训练

在 sky masks 就绪后，运行修复后的训练脚本：

```bash
bash /home/luosx/3dgs/run_train_omnire.sh
```

训练过程（30k iterations）预计 2-4 小时（RTX 4090 级别 GPU）。训练 log 保存到 `data/train_omnire_v1.log`。

**逻辑：** OmniRe 与 splatfacto 的核心差别在于：

- 背景、车辆、行人分别用独立 Gaussian graph 建模，不相互污染
- sky mask 保护背景 Gaussians 不被天空拉扯
- 10Hz 数据（191帧 vs 当前 ~50帧）提供 4倍更强的多视角约束
- per-camera 仿射曝光补偿，处理各摄像头白平衡差异
- 内置位姿精化，不会像 v12 那样失控

### Step 5：评估并与 v13 对比

训练完成后：

```bash
conda activate drivestudio
cd /home/luosx/3dgs/drivestudio
python tools/eval.py \
    --resume_from /home/luosx/3dgs/data/checkpoints/omnire/scene_0061_omnire/scene-0061_omnire_v1
```

关注指标：PSNR（目标 ≥ 24dB，v13 估计在 18-20dB 区间）、SSIM、视频可视化结果。

---

## 数据流图

```
NuScenes raw data
(nuscenes2mcap/data/)
        │
        ▼
preprocess.py ✓ 已完成
        │
        ▼
processed_10Hz_10Hz/mini/mini/
✓ images / lidar / calib / dynamic_masks
        │
        ├──────────────────────────────────┐
        ▼                                  ▼
extract_masks.py                    OmniRe 训练
(segformer env)                   (drivestudio env)
⚠ 需要重新运行                          │
        │                                  │
        ▼                                  │
sky_masks/ ✗ 目前为空 ──────────────────────┘
                                           │
                              SMPL humanpose (可选) ──┘
                                           │
                                           ▼
                              OmniRe 结果 预期 PSNR ~24-28dB
```

---

## 预期效果对比

| 维度 | v13 splatfacto | OmniRe（预期） |
|------|---------------|----------------|
| 前视质量 | 勉强可见道路结构，局部噪点 | 清晰道路/建筑/植被 |
| 后视质量 | 全屏噪点 | sky mask 消除天空污染，噪点显著减少 |
| 动态物体区域 | 模糊空洞（mask留下的） | 独立建模，可移除/替换 |
| 训练帧数 | ~50帧/摄像头（2Hz） | ~191帧/摄像头（10Hz） |
| 整体 PSNR 估计 | 18-20 dB | 24-28 dB |
