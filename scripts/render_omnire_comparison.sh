#!/bin/bash
# =============================================================================
# Render OmniRe output and compare with v11 splatfacto result
# Run AFTER run_train_omnire.sh completes
# =============================================================================
set -e

WORKSPACE=/home/luosx/3dgs
DRIVESTUDIO_DIR=$WORKSPACE/drivestudio
OUTPUT_ROOT=$WORKSPACE/data/checkpoints/omnire

eval "$(conda shell.bash hook)"
conda activate drivestudio
export PYTHONPATH=$DRIVESTUDIO_DIR

cd $DRIVESTUDIO_DIR

# Find the latest OmniRe checkpoint
CKPT=$(find $OUTPUT_ROOT -name "*.pth" | sort -V | tail -1)
echo "Using checkpoint: $CKPT"

# Render all cameras
python tools/eval.py \
    --resume_from $CKPT \
    --render_video \
    --output_dir $WORKSPACE/data/output/omnire

echo "OmniRe render saved to: $WORKSPACE/data/output/omnire"
echo ""
echo "Side-by-side comparison:"
echo "  v11 (splatfacto):  $WORKSPACE/data/output/scene-0061_sunny_v11_pruned.mp4"
echo "  OmniRe:            $WORKSPACE/data/output/omnire/"