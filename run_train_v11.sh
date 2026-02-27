#!/bin/bash
set -e
eval "$(conda shell.bash hook)"
conda activate 3dgs

export MAX_JOBS=2

# v11: 基于 v10 进一步优化噪点 — 更严格的 cull/densify 控制
ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v11 \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.03 \
  --pipeline.model.use-scale-regularization True \
  --pipeline.model.max-gauss-ratio 3.5 \
  --pipeline.model.stop-screen-size-at 15000 \
  --pipeline.model.cull-scale-thresh 0.25 \
  --pipeline.model.sh-degree 2 \
  --pipeline.model.densify-grad-thresh 0.0015 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v9 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none