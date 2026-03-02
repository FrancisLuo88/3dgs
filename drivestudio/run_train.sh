#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4

# 回滚到标准参数，只关闭 viewer
ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v4 \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v4 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
