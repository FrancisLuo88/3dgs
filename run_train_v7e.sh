#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# 启动 v7e 训练 (防死锁版)
# 策略：
# 1. stop-split-at 7000: 在 7000 步停止分裂/克隆 Gaussian。
#    - 之前在 7720 步卡死，怀疑是 densification 导致的计算/内存死锁。
#    - 提前停止分裂，固定 Gaussian 数量，后续只优化参数。
# 2. cull-alpha-thresh 0.1: 保持去雾。
# 3. 使用 v7d 数据集 (无 Mask)，确保纯净背景。

ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v7e \
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
