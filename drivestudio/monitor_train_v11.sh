#!/bin/bash

echo "=== V11 训练监控 ==="
echo "开始时间: $(date)"
echo

while true; do
    echo "=== $(date) ==="
    
    # 检查进程状态
    if pgrep -f "scene-0061_s0_v11" > /dev/null; then
        echo "✅ V11 训练进程运行中"
        
        # 查找最新的日志文件并提取进度
        LOG_DIR="/home/luosx/3dgs/data/checkpoints/scene-0061_s0_v11"
        if [ -d "$LOG_DIR" ]; then
            # 查找最新的训练目录
            LATEST_DIR=$(find "$LOG_DIR" -name "splatfacto" -type d | head -1)
            if [ -n "$LATEST_DIR" ]; then
                LATEST_SUBDIR=$(find "$LATEST_DIR" -maxdepth 1 -type d | tail -1)
                if [ -n "$LATEST_SUBDIR" ]; then
                    # 查找tensorboard事件文件
                    TB_FILE=$(find "$LATEST_SUBDIR" -name "events.out.tfevents.*" | head -1)
                    if [ -f "$TB_FILE" ]; then
                        echo "📊 Tensorboard日志: $TB_FILE"
                        echo "📈 文件大小: $(du -h "$TB_FILE" | cut -f1)"
                        echo "🕒 最后修改: $(stat -c %y "$TB_FILE")"
                    fi
                    
                    # 检查checkpoint
                    CKPT_DIR="$LATEST_SUBDIR/nerfstudio_models"
                    if [ -d "$CKPT_DIR" ]; then
                        LATEST_CKPT=$(ls -1 "$CKPT_DIR"/step-*.ckpt 2>/dev/null | sort -V | tail -1)
                        if [ -n "$LATEST_CKPT" ]; then
                            STEP=$(basename "$LATEST_CKPT" .ckpt | sed 's/step-0*//')
                            PROGRESS=$(echo "scale=1; $STEP * 100 / 30000" | bc -l)
                            echo "💾 最新checkpoint: step-$STEP (${PROGRESS}%)"
                        fi
                    fi
                fi
            fi
        fi
        
        # GPU使用率
        if command -v nvidia-smi &> /dev/null; then
            echo "🎮 GPU状态:"
            nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | \
            awk '{printf "   GPU利用率: %s%%, 显存: %s/%s MB\n", $1, $2, $3}'
        fi
        
    else
        echo "❌ V11 训练进程未运行"
        
        # 检查是否完成
        FINAL_CKPT="/home/luosx/3dgs/data/checkpoints/scene-0061_s0_v11/splatfacto/*/nerfstudio_models/step-000029999.ckpt"
        if ls $FINAL_CKPT 2>/dev/null; then
            echo "🎉 V11 训练已完成！"
            break
        fi
    fi
    
    echo "----------------------------------------"
    sleep 30
done

echo "监控结束: $(date)"