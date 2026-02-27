#!/bin/bash
# =============================================================================
# Train OmniRe (DriveStudio) on NuScenes scene-0061
# Run AFTER environments/drivestudio_setup.sh completes
#
# scene-0061 is index 000 in the NuScenes mini processed output
# =============================================================================
set -e

WORKSPACE=/home/luosx/3dgs
DRIVESTUDIO_DIR=$WORKSPACE/drivestudio
NUSCENES_PROCESSED=$WORKSPACE/data/drivestudio_nuscenes/processed_10Hz

eval "$(conda shell.bash hook)"
conda activate drivestudio
export PYTHONPATH=$DRIVESTUDIO_DIR
export MAX_JOBS=2

cd $DRIVESTUDIO_DIR

SCENE_IDX=000   # scene-0061 is the first scene in mini
OUTPUT_ROOT=$WORKSPACE/data/checkpoints/omnire
RUN_NAME=scene-0061_omnire_v1

echo "================================================================="
echo " Training OmniRe on NuScenes scene-0061"
echo " Output: $OUTPUT_ROOT/$RUN_NAME"
echo "================================================================="

# omnire_extended_cam.yaml is recommended for 6+ camera setups
python tools/train.py \
    --config_file configs/omnire_extended_cam.yaml \
    --output_root $OUTPUT_ROOT \
    --project scene_0061_omnire \
    --run_name $RUN_NAME \
    dataset=nuscenes/6cams \
    data.scene_idx=$SCENE_IDX \
    data.start_timestep=0 \
    data.end_timestep=-1 \
    data.data_root=$WORKSPACE/data/drivestudio_nuscenes \
    2>&1 | tee $WORKSPACE/data/train_omnire_v1.log

echo "================================================================="
echo " Training complete!"
echo " Eval: python tools/eval.py --resume_from $OUTPUT_ROOT/scene_0061_omnire/$RUN_NAME"
echo "================================================================="