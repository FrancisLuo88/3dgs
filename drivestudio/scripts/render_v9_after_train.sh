#!/bin/bash
# Run this after v9 training completes to render scene-0061_sunny_v9.mp4
set -e
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs

CKPT=$(find /home/luosx/3dgs/data/checkpoints/scene-0061_s0_v9 -name "step-000029999.ckpt" -o -name "step-000030000.ckpt" 2>/dev/null | head -1)
if [ -z "$CKPT" ]; then
  echo "No final checkpoint found. Use latest step-*.ckpt?"
  CKPT=$(find /home/luosx/3dgs/data/checkpoints/scene-0061_s0_v9 -name "step-*.ckpt" 2>/dev/null | sort -V | tail -1)
fi
if [ -z "$CKPT" ]; then
  echo "No checkpoint found."
  exit 1
fi
CKPT_DIR=$(dirname "$CKPT")
echo "Using checkpoint dir: $CKPT_DIR"

python /home/luosx/3dgs/scripts/render_multicam_video.py \
  --checkpoint "$CKPT_DIR" \
  --mcap /home/luosx/3dgs/data/input/NuScenes-v1.0-mini-scene-0061.mcap \
  --scene-data /home/luosx/3dgs/data/scenes/scene-0061_s0_v9 \
  --output /home/luosx/3dgs/data/output/scene-0061_sunny_v9.mp4

echo "Done: data/output/scene-0061_sunny_v9.mp4"
