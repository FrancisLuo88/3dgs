#!/usr/bin/env python3
"""Prune floater Gaussians from a trained splatfacto checkpoint and render video.

Floaters are identified by:
  1. Low opacity (sigmoid(raw) < min_opacity)
  2. Excessively large 3D scale (max(exp(raw)) > max_scale)
  3. Extreme scale anisotropy (max/min > max_ratio)

Usage:
  python scripts/prune_and_render.py \
    --config <config.yml path> \
    --scene-data <scene dir with transforms.json> \
    --output <output.mp4>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch


def load_pipeline(config_path: Path):
    from nerfstudio.utils.eval_utils import eval_setup
    _, pipeline, _, _ = eval_setup(
        config_path,
        eval_num_rays_per_chunk=None,
        test_mode="inference",
    )
    return pipeline


def prune_gaussians(pipeline, min_opacity=0.05, max_scale=0.15, max_ratio=8.0):
    """Remove outlier Gaussians in-place. Returns (kept, removed) counts."""
    model = pipeline.model
    device = model.device

    with torch.no_grad():
        opacities_raw = model.gauss_params["opacities"].squeeze(-1)
        scales_raw = model.gauss_params["scales"]

        opacities = torch.sigmoid(opacities_raw)
        scales = torch.exp(scales_raw)

        n_before = opacities.shape[0]

        keep_opacity = opacities >= min_opacity

        scale_max = scales.max(dim=-1).values
        keep_scale = scale_max <= max_scale

        scale_min = scales.min(dim=-1).values.clamp(min=1e-8)
        ratio = scale_max / scale_min
        keep_ratio = ratio <= max_ratio

        keep = keep_opacity & keep_scale & keep_ratio

        n_kept = keep.sum().item()
        n_removed = n_before - n_kept

        print(f"[Prune] Before: {n_before:,} Gaussians")
        print(f"  Low opacity (<{min_opacity}): {(~keep_opacity).sum().item():,}")
        print(f"  Large scale  (>{max_scale}):  {(~keep_scale).sum().item():,}")
        print(f"  Extreme ratio (>{max_ratio}): {(~keep_ratio).sum().item():,}")
        print(f"[Prune] After:  {n_kept:,} Gaussians (removed {n_removed:,})")

        for name in ["means", "scales", "quats", "features_dc", "features_rest", "opacities"]:
            old = model.gauss_params[name]
            model.gauss_params[name] = torch.nn.Parameter(old[keep].contiguous())

    return n_kept, n_removed


def render_video(pipeline, scene_data_dir: Path, output_path: Path, dp_transform: dict):
    """Render multi-camera video using the pruned model."""
    import cv2
    from nerfstudio.cameras.cameras import Cameras, CameraType

    with open(scene_data_dir / "transforms.json") as f:
        transforms = json.load(f)

    CAM_GRID = [
        ["CAM_FRONT_LEFT", "CAM_FRONT", "CAM_FRONT_RIGHT"],
        ["CAM_BACK_LEFT", "CAM_BACK", "CAM_BACK_RIGHT"],
    ]
    CELL_W, CELL_H, LABEL_H, FPS = 800, 450, 30, 12
    device = pipeline.device

    cam_frames: dict[str, list[dict]] = {}
    for frame in transforms["frames"]:
        cam_id = frame.get("camera_id", "UNKNOWN")
        cam_frames.setdefault(cam_id, []).append(frame)

    n_frames = min(len(v) for v in cam_frames.values())
    print(f"[Render] {n_frames} frames x {len(cam_frames)} cameras")

    T_mat = np.array(dp_transform["transform"], dtype=np.float64)
    scale = float(dp_transform["scale"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    grid_w = CELL_W * 3
    grid_h = (CELL_H + LABEL_H) * 2
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, FPS, (grid_w, grid_h))

    for fi in range(n_frames):
        if fi % 10 == 0:
            print(f"[Render] {fi}/{n_frames} ({fi/n_frames*100:.0f}%)")
        cam_imgs = {}
        for cam_id in [c for row in CAM_GRID for c in row]:
            frames_for_cam = cam_frames.get(cam_id)
            if not frames_for_cam or fi >= len(frames_for_cam):
                cam_imgs[cam_id] = None
                continue
            fr = frames_for_cam[fi]
            c2w = np.array(fr["transform_matrix"], dtype=np.float64)
            pos = c2w[:3, 3]
            pos_t = T_mat[:3, :3] @ pos + T_mat[:3, 3]
            c2w[:3, 3] = pos_t * scale

            fx = fr.get("fl_x", transforms["fl_x"])
            fy = fr.get("fl_y", transforms["fl_y"])
            cx = fr.get("cx", transforms["cx"])
            cy = fr.get("cy", transforms["cy"])
            W = fr.get("w", transforms["w"])
            H = fr.get("h", transforms["h"])

            c2w_t = torch.from_numpy(c2w[:3, :4]).float().unsqueeze(0).to(device)
            camera = Cameras(
                camera_to_worlds=c2w_t,
                fx=torch.tensor([fx], dtype=torch.float32, device=device),
                fy=torch.tensor([fy], dtype=torch.float32, device=device),
                cx=torch.tensor([cx], dtype=torch.float32, device=device),
                cy=torch.tensor([cy], dtype=torch.float32, device=device),
                width=torch.tensor([W], dtype=torch.int32, device=device),
                height=torch.tensor([H], dtype=torch.int32, device=device),
                camera_type=CameraType.PERSPECTIVE,
            )
            with torch.no_grad():
                outputs = pipeline.model.get_outputs_for_camera(camera)
            rgb = outputs["rgb"].detach().cpu().numpy()
            cam_imgs[cam_id] = (rgb * 255).clip(0, 255).astype(np.uint8)

        rows = []
        for row_cams in CAM_GRID:
            cells = []
            for cam_id in row_cams:
                img = cam_imgs.get(cam_id)
                cell = np.zeros((CELL_H + LABEL_H, CELL_W, 3), dtype=np.uint8)
                cell[:LABEL_H, :] = (40, 40, 40)
                cv2.putText(cell, cam_id, (8, LABEL_H - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA)
                if img is not None:
                    cell[LABEL_H:, :] = cv2.resize(img, (CELL_W, CELL_H))
                cells.append(cell)
            rows.append(np.hstack(cells))
        grid = np.vstack(rows)
        writer.write(cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))

    writer.release()
    print(f"[Render] Saved: {output_path} ({n_frames} frames @ {FPS}fps)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to config.yml")
    parser.add_argument("--scene-data", required=True, help="Scene directory with transforms.json")
    parser.add_argument("--output", required=True, help="Output MP4 path")
    parser.add_argument("--min-opacity", type=float, default=0.05)
    parser.add_argument("--max-scale", type=float, default=0.15)
    parser.add_argument("--max-ratio", type=float, default=8.0)
    args = parser.parse_args()

    config_path = Path(args.config)
    scene_data = Path(args.scene_data)

    print("[Load] Loading pipeline...")
    pipeline = load_pipeline(config_path)
    print(f"[Load] Model on {pipeline.device}, {pipeline.model.num_points:,} Gaussians")

    prune_gaussians(pipeline, args.min_opacity, args.max_scale, args.max_ratio)

    dp_path = config_path.parent / "dataparser_transforms.json"
    if not dp_path.exists():
        print(f"[Error] Missing {dp_path}")
        sys.exit(1)
    with open(dp_path) as f:
        dp_transform = json.load(f)

    render_video(pipeline, scene_data, Path(args.output), dp_transform)


if __name__ == "__main__":
    main()
