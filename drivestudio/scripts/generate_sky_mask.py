#!/usr/bin/env python3
"""Generate sky masks and merge them into existing dynamic-object masks.

Sky detection uses a two-stage approach:
  1. HSV pixel classification: high brightness + low saturation (daytime sky)
     OR high saturation blue-cyan hue (blue sky)
  2. Connectivity filter: only sky pixels connected to the top image border are kept
     (avoids marking white cars/buildings as sky)

Merged mask convention (nerfstudio):
  White (255) = keep (train on this pixel)
  Black (0)   = ignore (sky OR dynamic object)

Usage:
  python scripts/generate_sky_mask.py --scene-dir /path/to/scene_v12
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import cv2
import numpy as np


def detect_sky(bgr: np.ndarray) -> np.ndarray:
    """Return binary sky mask (255=sky) via HSV thresholding + connectivity."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.int32)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    H, W = bgr.shape[:2]

    # --- pixel-level candidates ---
    # Overcast / light grey sky: low sat, high val
    overcast = (s < 40) & (v > 160)

    # Blue sky: hue in [90..130] (blue-cyan range in OpenCV 0-180), moderate-high val
    blue = (h >= 90) & (h <= 130) & (s > 20) & (v > 100)

    # Sunset / haze: low sat, high val OR pinkish-orange hue, high val
    haze = (s < 60) & (v > 200)

    sky_candidates = (overcast | blue | haze).astype(np.uint8) * 255

    # --- morphological clean-up ---
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    sky_candidates = cv2.morphologyEx(sky_candidates, cv2.MORPH_CLOSE, kernel)
    sky_candidates = cv2.morphologyEx(sky_candidates, cv2.MORPH_OPEN,
                                       cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    # --- connectivity: keep only regions touching the top border ---
    # Flood-fill from each pixel on the top row that is a sky candidate
    filled = np.zeros((H + 2, W + 2), np.uint8)
    seed_mask = sky_candidates.copy()
    for x in range(W):
        if sky_candidates[0, x] == 255:
            cv2.floodFill(seed_mask, filled, (x, 0), 128,
                          loDiff=(15, 15, 15), upDiff=(15, 15, 15),
                          flags=cv2.FLOODFILL_FIXED_RANGE | (4 | cv2.FLOODFILL_MASK_ONLY << 8))

    sky_connected = (seed_mask == 128).astype(np.uint8) * 255

    # As a fallback, use the raw candidates but limit to upper portion of the image
    # to catch skies that weren't perfectly filled
    upper_raw = sky_candidates.copy()
    upper_raw[H // 2:, :] = 0  # only allow sky above mid-line if not connectivity-found

    sky_final = cv2.bitwise_or(sky_connected, upper_raw)

    # Final clean-up
    sky_final = cv2.morphologyEx(sky_final, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
    sky_final = cv2.morphologyEx(sky_final, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))

    return sky_final


def process_scene(scene_dir: Path, dry_run: bool = False) -> None:
    images_dir = scene_dir / "images"
    masks_dir = scene_dir / "masks"
    masks_dir.mkdir(exist_ok=True)

    image_files = sorted(images_dir.glob("*.jpg")) + sorted(images_dir.glob("*.png"))
    total = len(image_files)
    sky_pixel_stats = {}

    for i, img_path in enumerate(image_files):
        if i % 30 == 0:
            print(f"  [{i}/{total}] {img_path.name}")

        bgr = cv2.imread(str(img_path))
        if bgr is None:
            print(f"  WARN: cannot read {img_path}")
            continue

        sky = detect_sky(bgr)

        # Derive mask filename from image filename
        stem = img_path.stem  # e.g. CAM_BACK_frame_0000
        # Replace _frame_ with _mask_ and use .png
        mask_name = stem.replace("_frame_", "_mask_") + ".png"
        mask_path = masks_dir / mask_name

        if mask_path.exists():
            existing = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if existing is None:
                existing = np.ones(bgr.shape[:2], dtype=np.uint8) * 255
        else:
            existing = np.ones(bgr.shape[:2], dtype=np.uint8) * 255  # all white = keep

        # Merge: black out sky pixels on top of existing mask
        # sky==255 means "this is sky" → set to 0 (ignore)
        merged = existing.copy()
        merged[sky == 255] = 0

        cam_id = stem.split("_frame_")[0]
        sky_frac = (sky == 255).mean()
        sky_pixel_stats.setdefault(cam_id, []).append(sky_frac)

        if not dry_run:
            cv2.imwrite(str(mask_path), merged)

    print("\n  Sky coverage summary (avg per camera):")
    for cam, fracs in sorted(sky_pixel_stats.items()):
        print(f"    {cam}: {np.mean(fracs)*100:.1f}% sky avg "
              f"(min {np.min(fracs)*100:.1f}%, max {np.max(fracs)*100:.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-dir", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyse sky coverage without writing masks")
    args = parser.parse_args()

    scene_dir = Path(args.scene_dir)
    print(f"Processing sky masks for: {scene_dir}")
    process_scene(scene_dir, dry_run=args.dry_run)
    print("Done.")


if __name__ == "__main__":
    main()
