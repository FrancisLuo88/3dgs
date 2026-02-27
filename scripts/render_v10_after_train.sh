#!/bin/bash
# 训练完成后运行，渲染 scene-0061_sunny_v10.mp4
set -e
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs

CKPT=$(find /home/luosx/3dgs/data/checkpoints/scene-0061_s0_v10 -name "step-000029999.ckpt" -o -name "step-000030000.ckpt" 2>/dev/null | head -1)
if [ -z "$CKPT" ]; then
  CKPT=$(find /home/luosx/3dgs/data/checkpoints/scene-0061_s0_v10 -name "step-*.ckpt" 2>/dev/null | sort -V | tail -1)
fi
if [ -z "$CKPT" ]; then
  echo "No v10 checkpoint found."
  exit 1
fi
CKPT_DIR=$(dirname "$CKPT")
echo "Using: $CKPT_DIR"

python /home/luosx/3dgs/scripts/render_multicam_video.py \
  --checkpoint "$CKPT_DIR" \
  --mcap /home/luosx/3dgs/data/input/NuScenes-v1.0-mini-scene-0061.mcap \
  --scene-data /home/luosx/3dgs/data/scenes/scene-0061_s0_v9 \
  --output /home/luosx/3dgs/data/output/scene-0061_sunny_v10.mp4

echo "Done: data/output/scene-0061_sunny_v10.mp4"
