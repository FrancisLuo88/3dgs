#!/bin/bash
set -e
eval "$(conda shell.bash hook)"
conda activate 3dgs

export MAX_JOBS=2

# v13: 回退到 v11 已验证配置，作为稳定基线
#  - 使用 v9 数据（无天空遮罩，只有动态物体遮罩）
#  - 不开启 camera optimizer（v12 教训：数据不足时 SO3xR3 会乱跑）
#  - 所有参数与 v11 完全一致
ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v13 \
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