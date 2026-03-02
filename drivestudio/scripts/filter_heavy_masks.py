#!/usr/bin/env python3
"""Remove frames whose mask has >50% black (masked) pixels from transforms.json.

Heavily masked frames give zero loss signal and cause unconstrained Gaussians.
Usage:
  python scripts/filter_heavy_masks.py <scene_dir>
Example:
  python scripts/filter_heavy_masks.py data/scenes/scene-0061_s0_v9
"""
from pathlib import Path
import json
import sys
import cv2


def main():
    if len(sys.argv) < 2:
        print("Usage: python filter_heavy_masks.py <scene_dir>")
        sys.exit(1)
    scene_dir = Path(sys.argv[1])
    transforms_path = scene_dir / "transforms.json"
    if not transforms_path.exists():
        print(f"Not found: {transforms_path}")
        sys.exit(1)

    with open(transforms_path) as f:
        data = json.load(f)

    threshold = 0.5  # remove if black fraction > 50%
    kept = []
    removed = []

    for frame in data["frames"]:
        mask_path = frame.get("mask_path")
        if not mask_path:
            kept.append(frame)
            continue
        mask_full = scene_dir / mask_path
        if not mask_full.exists():
            kept.append(frame)
            continue
        img = cv2.imread(str(mask_full), cv2.IMREAD_GRAYSCALE)
        if img is None:
            kept.append(frame)
            continue
        total = img.size
        black = (img == 0).sum()
        frac_black = black / total
        if frac_black > threshold:
            removed.append((mask_path, round(frac_black * 100, 1)))
        else:
            kept.append(frame)

    data["frames"] = kept
    with open(transforms_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Removed {len(removed)} frames (mask >{threshold*100:.0f}% black). Kept {len(kept)} frames.")
    for path, pct in removed:
        print(f"  - {path}: {pct}% black")


if __name__ == "__main__":
    main()
