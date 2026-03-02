#!/bin/bash
# 3DGS & WSL 极限资源探针脚本
# 每 2 秒记录一次系统状态，直到断联。重连后可查看日志分析死因。

LOG_FILE="wsl_crash_probe.log"
echo "System Probe Started. Logging to $LOG_FILE..."
echo "Time | System RAM (Free) | Swap (Free) | GPU VRAM (Used) | CPU Load" > $LOG_FILE

while true; do
    TIME=$(date '+%H:%M:%S')
    # 抓取系统可用内存
    RAM=$(free -m | awk '/^Mem:/{print $4}')
    # 抓取可用交换区
    SWAP=$(free -m | awk '/^Swap:/{print $4}')
    # 抓取 CUDA 显存占用 (捕捉驱动崩溃的异常)
    GPU=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -n 1 || echo "DRV_ERR")
    # 抓取系统 1 分钟平均负载
    LOAD=$(cat /proc/loadavg | awk '{print $1}')
    
    echo "$TIME | ${RAM}MB | ${SWAP}MB | ${GPU}MB | $LOAD" >> $LOG_FILE
    # 同步写入磁盘，防止宿主机突然断电或系统硬死机导致日志丢失
    sync
    sleep 2
done
