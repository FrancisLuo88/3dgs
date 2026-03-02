#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# 启动 v7 训练
# 优化策略：
# 1. 恢复 cull-alpha-thresh 到默认 0.1 (v6 误设为 0.005 导致保留了大量半透明模糊噪声)
# 2. 降低 densify-grad-thresh 到 0.0002 (更激进的加密，提升细节清晰度)
# 3. 提高 sh-degree 到 4 (增强光照/反射细节)
# 4. 继续使用 v6 数据集 (Mask 正确)

ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v7 \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.1 \
  --pipeline.model.densify-grad-thresh 0.0002 \
  --pipeline.model.sh-degree 4 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v6 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
