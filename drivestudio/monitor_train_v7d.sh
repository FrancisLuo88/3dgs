#!/bin/bash
LOG_FILE="/home/luosx/.cursor/projects/home-luosx-3dgs/terminals/190991.txt" # Log of the actual ns-train process
TARGET_PID=83952 # PID of the current ns-train process

echo "Monitoring ns-train (PID: $TARGET_PID)... Log: $LOG_FILE"

# 120 次 x 10秒 = 20分钟
for i in $(seq 1 120); do
  # 1. GPU资源监控
  gpu_info=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null)
  if [ -z "$gpu_info" ]; then
      gpu_util="N/A"
      gpu_mem="N/A"
  else
      gpu_util=$(echo $gpu_info | cut -d',' -f1)
      gpu_mem=$(echo $gpu_info | cut -d',' -f2)
  fi
  
  # 2. 进度监控
  last_line=$(grep -E "[0-9]+.*\\([0-9.]*\\%\\)" "$LOG_FILE" | tail -1)
  
  if [ -z "$last_line" ]; then
    step="Init"
    percent=""
  else
    step=$(echo "$last_line" | awk '{print $1}')
    percent=$(echo "$last_line" | awk '{print $2}')
  fi
  
  # 3. 进程状态监控
  if ps -p "$TARGET_PID" > /dev/null 2>&1; then
    status="RUNNING"
  else
    status="STOPPED"
  fi
  
  echo "[$(date +%H:%M:%S)] Status: $status | Step: $step $percent | GPU: ${gpu_util}% ${gpu_mem}MiB"
  
  if [ "$status" == "STOPPED" ]; then
    echo ">>> Training Process Stopped <<<"
    if grep -q "Finished training" "$LOG_FILE"; then
        echo ">>> 训练成功完成！<<<"
    else
        echo ">>> 训练异常退出，最后 10 行日志：<<<"
        tail -10 "$LOG_FILE"
    fi
    break
  fi
  
  sleep 10
done
