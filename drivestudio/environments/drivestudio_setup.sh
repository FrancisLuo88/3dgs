#!/bin/bash
# =============================================================================
# DriveStudio (OmniRe) Complete Setup Script
# Run from a regular WSL terminal (NOT inside Cursor)
#
# Usage:
#   chmod +x /home/luosx/3dgs/environments/drivestudio_setup.sh
#   bash /home/luosx/3dgs/environments/drivestudio_setup.sh
#
# What this script does:
#   Step 1 — Clone DriveStudio
#   Step 2 — Create conda env and install dependencies
#   Step 3 — Process NuScenes data to 10Hz (dramatically more frames than current 2Hz)
#   Step 4 — Generate sky & dynamic masks (SegFormer, separate env)
#   Step 5 — Train OmniRe on scene-0061
# =============================================================================
set -e

WORKSPACE=/home/luosx/3dgs
DRIVESTUDIO_DIR=$WORKSPACE/drivestudio
NUSCENES_RAW=$WORKSPACE/data/nuscenes2mcap/data   # has v1.0-mini/, samples/, sweeps/
NUSCENES_PROCESSED=$WORKSPACE/data/drivestudio_nuscenes/processed_10Hz

echo "================================================================="
echo " DriveStudio Setup — $(date)"
echo "================================================================="

# ── Step 1: Clone ────────────────────────────────────────────────────
if [ ! -d "$DRIVESTUDIO_DIR" ]; then
    echo "[1/5] Cloning DriveStudio..."
    cd $WORKSPACE
    git clone --recursive https://github.com/ziyc/drivestudio.git
else
    echo "[1/5] DriveStudio already cloned."
fi

cd $DRIVESTUDIO_DIR

# ── Step 2: Create conda env ─────────────────────────────────────────
echo "[2/5] Setting up conda environment 'drivestudio'..."
eval "$(conda shell.bash hook)"

if ! conda env list | grep -q "^drivestudio "; then
    conda create -n drivestudio python=3.9 -y
fi

conda activate drivestudio

export CUDA_HOME=$(dirname $(dirname $(which nvcc)))
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH


echo "  Installing requirements..."
pip install numpy==1.23.5 scipy
pip install chumpy --no-build-isolation

pip install -r requirements.txt
pip install nuscenes-devkit  # required for NuScenes preprocessing

echo "  Installing gsplat v1.3.0..."
MAX_JOBS=2 pip install "git+https://github.com/nerfstudio-project/gsplat.git@v1.3.0" --no-build-isolation

echo "  Installing pytorch3d..."
MAX_JOBS=2 pip install "git+https://github.com/facebookresearch/pytorch3d.git" --no-build-isolation

echo "  Installing nvdiffrast..."
pip install "git+https://github.com/NVlabs/nvdiffrast" --no-build-isolation

echo "  Installing SMPL-X..."
cd $DRIVESTUDIO_DIR/third_party/smplx && pip install -e . && cd $DRIVESTUDIO_DIR

echo "[2/5] Environment ready."

# ── Step 3: Preprocess NuScenes data to 10Hz ─────────────────────────
# This is the KEY IMPROVEMENT over our current approach:
# - Current: ~50 frames/camera at 2Hz
# - After processing: ~250 frames/camera at 10Hz (interpolate_N=4)
# - 5x more training data = dramatically better reconstruction quality

echo "[3/5] Preprocessing NuScenes data to 10Hz..."
mkdir -p $NUSCENES_PROCESSED

# Link raw data where DriveStudio expects it
mkdir -p $WORKSPACE/data/drivestudio_nuscenes
if [ ! -e "$WORKSPACE/data/drivestudio_nuscenes/nuscenes" ]; then
    ln -s $NUSCENES_RAW $WORKSPACE/data/drivestudio_nuscenes/nuscenes
fi

export PYTHONPATH=$DRIVESTUDIO_DIR

# Process all 10 scenes in mini split
# --interpolate_N 4 → 10Hz from 2Hz keyframes (5x frame density improvement)
python datasets/preprocess.py \
    --data_root $NUSCENES_RAW \
    --target_dir $NUSCENES_PROCESSED/mini \
    --dataset nuscenes \
    --split v1.0-mini \
    --start_idx 0 \
    --num_scenes 10 \
    --interpolate_N 4 \
    --workers 4 \
    --process_keys images lidar calib dynamic_masks objects

echo "[3/5] NuScenes data processed."

# ── Step 4: Sky masks via SegFormer ──────────────────────────────────
# Sky masks are CRITICAL for preventing sky pixels from contaminating
# Gaussian reconstruction (this was the root cause of back-camera noise)

echo "[4/5] Setting up SegFormer for sky mask extraction..."

if ! conda env list | grep -q "^segformer "; then
    conda create -n segformer python=3.8 -y
    conda activate segformer
    pip install torch==1.8.1+cu111 torchvision==0.9.1+cu111 torchaudio==0.8.1 \
        -f https://download.pytorch.org/whl/torch_stable.html
    pip install timm==0.3.2 pylint debugpy opencv-python-headless attrs ipython \
        tqdm imageio scikit-image omegaconf
    pip install mmcv-full==1.2.7 --no-cache-dir
    # Clone and install SegFormer
    cd /tmp && git clone https://github.com/NVlabs/SegFormer
    cd /tmp/SegFormer && pip install .
    cd $DRIVESTUDIO_DIR
    SEGFORMER_PATH=/tmp/SegFormer

    echo "  Downloading SegFormer checkpoint (segformer.b5 cityscapes)..."
    mkdir -p $SEGFORMER_PATH/pretrained
    # Try official download via gdown
    pip install gdown
    gdown 1e7DECAH0TRtPZM6hTqRGoboq1XPqSmuj -O $SEGFORMER_PATH/pretrained/segformer.b5.1024x1024.city.160k.pth
else
    conda activate segformer
    SEGFORMER_PATH=/tmp/SegFormer
fi

conda activate segformer
export PYTHONPATH=$DRIVESTUDIO_DIR

python $DRIVESTUDIO_DIR/datasets/tools/extract_masks.py \
    --data_root $NUSCENES_PROCESSED/mini \
    --segformer_path $SEGFORMER_PATH \
    --checkpoint $SEGFORMER_PATH/pretrained/segformer.b5.1024x1024.city.160k.pth \
    --start_idx 0 \
    --num_scenes 10 \
    --process_dynamic_mask

echo "[4/5] Sky and dynamic masks extracted."

# ── Step 5: Download human pose data (optional) ───────────────────────
echo "[5/5] Optionally download preprocessed human pose data..."
echo "  (Skip if no pedestrians in scene or if storage is limited)"
# pip install gdown
# cd $WORKSPACE/data/drivestudio_nuscenes
# gdown 1Z0gJVRtPnjvusQVaW7ghZnwfycZStCZx
# unzip nuscenes_preprocess_humanpose.zip
# rm nuscenes_preprocess_humanpose.zip

echo "================================================================="
echo " Setup complete! scene-0061 is scene index 000"
echo ""
echo " To train OmniRe:"
echo "   bash /home/luosx/3dgs/run_train_omnire.sh"
echo "================================================================="