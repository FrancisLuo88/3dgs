LOG_FILE="/home/luosx/3dgs/data/train_v7.log"
# 明确指定要监控的目标PID（74888，从你的ps结果中获取）
TARGET_PID=74888

for i in $(seq 1 35); do
  # 1. GPU资源监控（保留原逻辑）
  gpu_info=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits)
  gpu_util=$(echo $gpu_info | cut -d',' -f1)
  gpu_mem=$(echo $gpu_info | cut -d',' -f2)
  
  # 2. 进度监控（放宽正则，适配更多日志格式）
  # 原正则过严，改为匹配任意含“数字+(百分比)”的行，兼容日志格式差异
  last_line=$(grep -E "[0-9]+.*\([0-9.]*\%\)" $LOG_FILE | tail -1)
  
  if [ -z "$last_line" ]; then
    step="Init"
    percent=""
  else
    # 提取第一个数字作为step，提取括号+百分比作为进度（兼容多格式）
    step=$(echo "$last_line" | grep -oE "[0-9]+" | head -1)
    percent=$(echo "$last_line" | grep -oE "\([0-9.]*\%\)")
  fi
  
  # 3. 进程状态监控（直接用固定PID 74888，替代不可靠的pid文件）
  if ps -p $TARGET_PID > /dev/null 2>&1; then
    status="RUNNING"
  else
    status="STOPPED"
  fi
  
  # 输出监控信息（格式不变）
  echo "[$(date +%H:%M:%S)] Status: $status | Step: $step $percent | GPU: ${gpu_util}% ${gpu_mem}MiB"
  
  # 进程停止后的逻辑（保留原逻辑）
  if [ "$status" == "STOPPED" ]; then
    if grep -q "Finished training" $LOG_FILE; then
        echo ">>> 训练成功完成！<<<"
    else
        echo ">>> 训练异常退出，最后 20 行日志：<<<"
        tail -20 $LOG_FILE
    fi
    break
  fi
  
  sleep 60
done
