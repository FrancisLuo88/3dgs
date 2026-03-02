# DriveStudio / OmniRe Migration Guide

## Why We're Migrating

The root cause of persistent noise in v9–v12 is **tool mismatch**: `nerfstudio splatfacto` is designed for static indoor scenes with cameras arranged around an object. Our use case (6-camera forward-driving outdoor scene) violates multiple core assumptions:

| Issue | splatfacto | OmniRe |
|-------|-----------|--------|
| Sky handling | No sky model → sky pixels become noisy Gaussians | Built-in sky sphere model |
| Dynamic objects | Masking only (leaks at edges) | Separate Gaussian graph per object |
| Camera pose accuracy | Assumed perfect | Built-in pose refinement (SO3xR3) |
| Exposure variation | Not handled | Affine exposure compensation per camera |
| Data density | 50 frames/cam at 2Hz | 250 frames/cam at 10Hz (interpolated) |
| LiDAR initialization | Generic | Native NuScenes LiDAR pipeline |

## Prerequisites

- WSL2 with internet access
- ~15 GB disk space for processed data
- RTX 2080 SUPER 8GB (already available)

## Step-by-Step Instructions

### 1. Run from a regular WSL terminal (NOT inside Cursor)

```bash
bash /home/luosx/3dgs/environments/drivestudio_setup.sh
```

This takes ~30–60 minutes and handles:
- Cloning DriveStudio
- Creating `drivestudio` conda env
- Processing NuScenes scene-0061 to 10Hz (vs current 2Hz)
- Extracting sky masks via SegFormer
- Extracting dynamic object masks

### 2. Train OmniRe

```bash
bash /home/luosx/3dgs/run_train_omnire.sh
```

Training uses `omnire_extended_cam.yaml` (recommended for 6+ cameras).
Logs saved to: `data/train_omnire_v1.log`

### 3. Render and compare

```bash
bash /home/luosx/3dgs/scripts/render_omnire_comparison.sh
```

Compare output in `data/output/omnire/` vs `data/output/scene-0061_sunny_v11_pruned.mp4`.

---

## Data Structure After Setup

```
data/
  drivestudio_nuscenes/
    nuscenes -> (symlink to nuscenes2mcap/data)
    processed_10Hz/
      mini/
        000/          # scene-0061
          images/     # ~250 frames × 6 cameras = 1500 images
          lidar/
          sky_masks/  # SegFormer sky segmentation
          dynamic_masks/
          extrinsics/
          intrinsics/
          objects/
```

## Expected Quality Improvements

| Metric | v11 + pruning (current) | OmniRe (expected) |
|--------|------------------------|-------------------|
| Back camera full-screen noise | Some frames | Should be eliminated (sky model) |
| Local foreground noise | Still present | Significantly reduced (10Hz data + pose refinement) |
| Dynamic car artifacts | Masked (leaky) | Separate Gaussian graph |
| Sky rendering | Noisy Gaussians | Clean sky sphere |
| Overall realism | ~40% | ~80%+ (ICLR 2025 results) |
