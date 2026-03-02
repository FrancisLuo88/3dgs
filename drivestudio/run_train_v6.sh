#!/bin/bash
source /home/luosx/miniconda3/etc/profile.d/conda.sh
conda activate 3dgs
export MAX_JOBS=4
export CUDA_VISIBLE_DEVICES=0

echo "=== Debug Info ==="
echo "Python: $(which python)"
echo "Nvidia-smi:"
nvidia-smi
echo "Torch CUDA Check:"
python -c "import torch; print(f'Torch: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'Device count: {torch.cuda.device_count()}'); print(f'Device name: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}')"
echo "=================="

# 启动 v6 训练
ns-train splatfacto \
  --output-dir /home/luosx/3dgs/data/checkpoints \
  --experiment-name scene-0061_s0_v6 \
  --max-num-iterations 30000 \
  --steps-per-save 5000 \
  --vis tensorboard \
  --pipeline.model.cull-alpha-thresh 0.005 \
  nerfstudio-data \
  --data /home/luosx/3dgs/data/scenes/scene-0061_s0_v6 \
  --auto-scale-poses True \
  --center-method focus \
  --orientation-method none
