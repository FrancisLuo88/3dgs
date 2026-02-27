#!/bin/bash
set -e
eval "$(conda shell.bash hook)"
conda activate 3dgs

export MAX_JOBS=2

echo "=== 等待 V11 训练完成 ==="
FINAL_CKPT_PATTERN="/home/luosx/3dgs/data/checkpoints/scene-0061_s0_v11/splatfacto/*/nerfstudio_models/step-000029999.ckpt"

while true; do
    if ls $FINAL_CKPT_PATTERN 2>/dev/null; then
        echo "✅ V11 训练完成，开始后处理渲染..."
        break
    else
        echo "⏳ 等待训练完成... $(date)"
        sleep 60
    fi
done

# 找到实际的config路径
CONFIG_DIR=$(dirname $(ls $FINAL_CKPT_PATTERN | head -1))/..
CONFIG="$CONFIG_DIR/config.yml"
SCENE="/home/luosx/3dgs/data/scenes/scene-0061_s0_v9"

echo "=== 开始激进后处理渲染 ==="
echo "Config: $CONFIG"
echo "Scene: $SCENE"

# 用激进参数后处理并渲染
python /home/luosx/3dgs/scripts/prune_and_render.py \
  --config "$CONFIG" \
  --scene-data "$SCENE" \
  --output "/home/luosx/3dgs/data/output/scene-0061_sunny_v11_pruned.mp4" \
  --min-opacity 0.10 \
  --max-scale 0.10 \
  --max-ratio 5.0

echo "🎉 V11 后处理渲染完成！"
echo "输出: /home/luosx/3dgs/data/output/scene-0061_sunny_v11_pruned.mp4"