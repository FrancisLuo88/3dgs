#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# v10: reduce noise (back 满屏噪点, front 局部噪点) — 保持 v9 数据与正则，仅收紧 cull/SH/densify
ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v10 \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.02 \
  --pipeline.model.use-scale-regularization True \
  --pipeline.model.max-gauss-ratio 4.0 \
  --pipeline.model.stop-screen-size-at 15000 \
  --pipeline.model.cull-scale-thresh 0.3 \
  --pipeline.model.sh-degree 2 \
  --pipeline.model.densify-grad-thresh 0.0012 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v9 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
