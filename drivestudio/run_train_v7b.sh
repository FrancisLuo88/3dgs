#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# 启动 v7b 训练 (折中参数)
# 优化策略：
# 1. cull-alpha-thresh = 0.1 (保持不变，消除模糊的核心)
# 2. densify-grad-thresh = 0.0004 (从 0.0002 放宽到 0.0004，防止点云爆炸导致卡死)
# 3. sh-degree = 4 (保持不变，增强光影)

ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v7b \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.1 \
  --pipeline.model.densify-grad-thresh 0.0004 \
  --pipeline.model.sh-degree 4 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v6 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
