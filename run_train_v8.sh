#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# 启动 v8 训练 (最终稳健版)
# 目标：解决竹叶噪声 + 解决模糊 + 解决 7720 步卡死
# 策略：
# 1. 数据集: v7d (无 Mask，纯净 LiDAR 初始化) -> 解决竹叶噪声 (v5Mask反了) & Mask边缘死锁
# 2. Cull Thresh: 0.1 -> 解决大片模糊 (v6太低)
# 3. Stop Split: 7000 -> 解决 7720 步卡死 (提前停止高斯分裂，规避计算瓶颈)
# 4. Grad Thresh: 0.0008 (默认) -> 保证稳定性

ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v8 \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.1 \
  --pipeline.model.densify-grad-thresh 0.0008 \
  --pipeline.model.stop-split-at 7000 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v7d \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
