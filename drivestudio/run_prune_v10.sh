#!/bin/bash
set -e
eval "$(conda shell.bash hook)"
conda activate 3dgs

export MAX_JOBS=2

CONFIG=/home/luosx/3dgs/data/checkpoints/scene-0061_s0_v10/splatfacto/2026-02-27_101350/config.yml
SCENE=/home/luosx/3dgs/data/scenes/scene-0061_s0_v9
OUTPUT=/home/luosx/3dgs/data/output/scene-0061_sunny_v10_pruned.mp4

python /home/luosx/3dgs/scripts/prune_and_render.py \
  --config "$CONFIG" \
  --scene-data "$SCENE" \
  --output "$OUTPUT" \
  --min-opacity 0.05 \
  --max-scale 0.15 \
  --max-ratio 8.0
