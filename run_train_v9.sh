#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# v9: fix blur root cause — filter heavy-mask frames + scale/screen regularization
ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v9 \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.01 \
  --pipeline.model.use-scale-regularization True \
  --pipeline.model.max-gauss-ratio 5.0 \
  --pipeline.model.stop-screen-size-at 15000 \
  --pipeline.model.cull-scale-thresh 0.3 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v9 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
