for i in $(seq 1 30); do
  avail=$(free -m | awk 'NR==2{print $7}')
  gpu=$(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits | tr ',' '/')
  cicc=$(ps aux | grep cicc | grep -v grep | wc -l)
  ckpt=$(find /home/luosx/3dgs/data/checkpoints/scene-0061_s0_v3 -name "step-*.ckpt" 2>/dev/null | wc -l)
  alive=$(ps aux | grep "envs/3dgs.*ns-train" | grep -v grep | wc -l)
  # 从 log 抓最新 Gaussian 数和 loss
  gs_info=$(grep -oE "Step [0-9]+: [0-9]+ GSs" /home/luosx/.cursor/projects/home-luosx-3dgs/terminals/598407.txt 2>/dev/null | tail -1)
  loss=$(grep "get_train_loss" /home/luosx/.cursor/projects/home-luosx-3dgs/terminals/598407.txt 2>/dev/null | tail -1 | grep -oE "[0-9]+\.[0-9]+")
  echo "[$(date +%H:%M:%S)] RAM=${avail}MB GPU=${gpu}MiB cicc=${cicc} ckpts=${ckpt} alive=${alive} | ${gs_info} loss=${loss}"
  [ "$alive" -eq 0 ] && [ "$ckpt" -gt 0 ] && echo ">>> 训练完成！<<<" && break
  sleep 60
done
