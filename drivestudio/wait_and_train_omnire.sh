#!/bin/bash
# =============================================================================
# 等待 sky mask 提取（全部 10 个场景）完成后，自动启动 OmniRe 训练
# 策略A：等全部完成再训练，避免 GPU OOM
#
# 用法：在 WSL 终端中：
#   bash /home/luosx/3dgs/wait_and_train_omnire.sh
# =============================================================================

MASK_PID=85764   # extract_masks.py 的 PID（从后台任务得到）
DATA_ROOT="/home/luosx/3dgs/data/drivestudio_nuscenes/processed_10Hz_10Hz/mini/mini"
EXPECTED_PER_SCENE=1146   # 191 timesteps × 6 cameras

echo "================================================================="
echo " 等待 sky mask 提取完成 (PID: $MASK_PID)"
echo " 全部 10 个场景完成后才会启动训练"
echo "================================================================="

# 等待提取进程彻底结束
while kill -0 $MASK_PID 2>/dev/null; do
    # 统计当前已完成的场景
    DONE=0
    for i in 000 001 002 003 004 005 006 007 008 009; do
        COUNT=$(ls "$DATA_ROOT/$i/sky_masks/" 2>/dev/null | wc -l)
        if [ "$COUNT" -ge "$EXPECTED_PER_SCENE" ]; then
            DONE=$((DONE + 1))
        fi
    done
    echo "[$(date '+%H:%M:%S')] sky mask 提取中... 已完成场景: $DONE/10"
    sleep 120
done

echo ""
echo "[$(date '+%H:%M:%S')] sky mask 提取进程已结束，验证数据完整性..."

# 验证所有场景的 sky_masks 是否齐全
ALL_OK=true
for i in 000 001 002 003 004 005 006 007 008 009; do
    COUNT=$(ls "$DATA_ROOT/$i/sky_masks/" 2>/dev/null | wc -l)
    echo "  scene $i: $COUNT sky masks"
    if [ "$COUNT" -lt 100 ]; then
        echo "  WARNING: scene $i 的 sky masks 数量偏少，请检查！"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo "WARNING: 部分场景 sky masks 可能不完整，请手动检查后决定是否继续训练。"
    echo "训练脚本：bash /home/luosx/3dgs/run_train_omnire.sh"
    exit 1
fi

echo ""
echo "[$(date '+%H:%M:%S')] 数据验证通过，等待 GPU 冷却 30 秒..."
sleep 30

echo "[$(date '+%H:%M:%S')] 启动 OmniRe 训练！"
bash /home/luosx/3dgs/run_train_omnire.sh
