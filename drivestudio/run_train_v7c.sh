#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# 启动 v7c 训练 (保活参数)
# 优化策略：
# 1. cull-alpha-thresh = 0.1 (核心坚持：必须消除雾气)
# 2. densify-grad-thresh = 0.0008 (大幅回退到默认值，防止 7700 步卡死)
# 3. sh-degree = 3 (回退到 3，减轻计算压力)

ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v7c \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.1 \
  --pipeline.model.densify-grad-thresh 0.0008 \
  --pipeline.model.sh-degree 3 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v6 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
