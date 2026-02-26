#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

# 启动 v7d 训练 (无 Mask 版 + 稳定性修正)
# 修正：增加 datamanager 限制，防止 WSL2 下多进程死锁/内存溢出
# 参数：
#   --pipeline.datamanager.num-processes 0  (禁用多进程数据加载，防止僵尸进程/死锁)
#   --pipeline.datamanager.num-workers 1    (最小化工作线程，防止竞争)
#   --pipeline.model.cull-alpha-thresh 0.1  (保持去雾)
#   --pipeline.model.densify-grad-thresh 0.0008 (保守加密)
#   --pipeline.model.sh-degree 3 (保守 SH)

ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v7d \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.1 \
  --pipeline.model.densify-grad-thresh 0.0008 \
  --pipeline.model.sh-degree 3 \
  --pipeline.datamanager.num-processes 0 \
  --pipeline.datamanager.num-workers 1 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v7d \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
