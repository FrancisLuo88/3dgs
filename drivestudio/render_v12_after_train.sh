#!/bin/bash
# Auto-render v12 (sky mask + camera optimizer) when training completes
# with the same aggressive post-processing as v11
set -e
eval "$(conda shell.bash hook)"
conda activate 3dgs
export MAX_JOBS=2

echo "=== Waiting for V12 training to complete ==="
FINAL_CKPT_PATTERN="/home/luosx/3dgs/data/checkpoints/scene-0061_s0_v12/splatfacto/*/nerfstudio_models/step-000029999.ckpt"

while true; do
    FOUND=$(ls $FINAL_CKPT_PATTERN 2>/dev/null | head -1)
    if [ -n "$FOUND" ]; then
        echo "✅ V12 training complete: $FOUND"
        break
    fi
    echo "⏳ $(date) — still training..."
    sleep 60
done

CONFIG=$(dirname $FOUND)/../config.yml
echo "Config: $CONFIG"

python /home/luosx/3dgs/scripts/prune_and_render.py \
    --config "$CONFIG" \
    --scene-data /home/luosx/3dgs/data/scenes/scene-0061_s0_v12 \
    --output /home/luosx/3dgs/data/output/scene-0061_sunny_v12_pruned.mp4 \
    --min-opacity 0.10 \
    --max-scale 0.10 \
    --max-ratio 5.0

echo "🎉 V12 render complete: /home/luosx/3dgs/data/output/scene-0061_sunny_v12_pruned.mp4"