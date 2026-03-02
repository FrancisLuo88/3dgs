#!/usr/bin/env python3
"""render_multicam_video.py — 从训练好的 3DGS checkpoint 渲染多路摄像头视频。

功能：
  1. 从 nerfstudio checkpoint 加载 splatfacto 模型
  2. 使用原始 MCAP 中提取的相机位姿逐帧渲染 6 路视图
  3. 将 6 路渲染结果拼成 3×2 网格（带相机标签）
  4. 导出 MP4 视频（12fps，H.264）

用法：
  python scripts/render_multicam_video.py \\
    --checkpoint data/checkpoints/scene-0061_s0/<timestamp>/splatfacto/<ts>/nerfstudio_models \\
    --mcap data/input/NuScenes-v1.0-mini-scene-0061.mcap \\
    --scene-data data/scenes/scene-0061_s0 \\
    --output data/output/scene-0061_sunny.mp4
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import cv2


# 6 路摄像头固定布局顺序（3 列 × 2 行）
CAM_GRID = [
    ["CAM_FRONT_LEFT",  "CAM_FRONT",  "CAM_FRONT_RIGHT"],
    ["CAM_BACK_LEFT",   "CAM_BACK",   "CAM_BACK_RIGHT"],
]

CELL_W, CELL_H = 800, 450     # 与训练分辨率一致（0.5x 缩放）
LABEL_H = 30                   # 标签栏高度（px）
FPS = 12


def find_latest_checkpoint(checkpoint_dir: str) -> Optional[Path]:
    """在 nerfstudio 输出目录中查找最新的 nerfstudio_models 目录。"""
    base = Path(checkpoint_dir)
    if not base.exists():
        return None
    # nerfstudio 结构: <exp>/<timestamp>/splatfacto/<timestamp>/nerfstudio_models/
    candidates = list(base.rglob("nerfstudio_models"))
    if not candidates:
        # 可能直接传入了 nerfstudio_models 路径
        if (base / "step-00000004999.ckpt").exists() or list(base.glob("step-*.ckpt")):
            return base
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_splatfacto_model(checkpoint_dir: Path):
    """从 nerfstudio checkpoint 加载 splatfacto pipeline。"""
    from nerfstudio.utils.eval_utils import eval_load_checkpoint
    from nerfstudio.pipelines.base_pipeline import Pipeline

    # nerfstudio 结构:
    #   <exp>/<ts>/config.yml
    #   <exp>/<ts>/nerfstudio_models/step-*.ckpt
    # checkpoint_dir 指向 nerfstudio_models/，config.yml 在其父目录
    config_path = checkpoint_dir.parent / "config.yml"

    if not config_path.exists():
        # 往上多找一层
        config_path = checkpoint_dir.parent.parent / "config.yml"

    if not config_path.exists():
        raise FileNotFoundError(f"找不到 config.yml，请确认 checkpoint 路径正确。\n  检查路径：{config_dir}")

    from nerfstudio.utils.eval_utils import eval_setup
    _, pipeline, _, _ = eval_setup(
        config_path,
        eval_num_rays_per_chunk=None,
        test_mode="inference",
    )
    return pipeline


def apply_dataparser_transform(c2w: np.ndarray, dp_transform: dict) -> np.ndarray:
    """将训练时 nerfstudio dataparser 的归一化变换应用到推理相机位姿。

    nerfstudio 在训练时对所有相机位姿做：
      pos_norm = scale × (T[:3,:3] @ pos_raw + T[:3,3])
      rot_norm = c2w[:3,:3]  (旋转部分不缩放)

    推理时必须用完全相同的变换，否则相机坐标和 Gaussian Splat 坐标空间不匹配。

    Args:
        c2w: 4×4 camera-to-world 原始位姿（transforms.json 中的值）
        dp_transform: dataparser_transforms.json 内容（含 "transform" 和 "scale"）

    Returns:
        归一化后的 4×4 c2w 矩阵（与训练时坐标空间一致）
    """
    T = np.array(dp_transform["transform"], dtype=np.float64)  # 3×4
    scale = float(dp_transform["scale"])

    c2w_out = c2w.copy().astype(np.float64)

    # 只变换平移部分（旋转列保持不变，只有量纲已归一化）
    pos = c2w[:3, 3]
    pos_transformed = T[:3, :3] @ pos + T[:3, 3]
    c2w_out[:3, 3] = pos_transformed * scale

    return c2w_out.astype(np.float32)


def render_frame_from_pipeline(
    pipeline,
    c2w: np.ndarray,
    fx: float, fy: float, cx: float, cy: float,
    W: int, H: int,
    dp_transform: dict | None = None,
) -> np.ndarray:
    """渲染单帧图像（返回 HxWx3 uint8 numpy 数组）。

    Args:
        dp_transform: dataparser_transforms.json 内容。必须传入，否则坐标空间不匹配。
    """
    from nerfstudio.cameras.cameras import Cameras, CameraType

    device = pipeline.device

    # 应用 dataparser 归一化（关键步骤）
    if dp_transform is not None:
        c2w = apply_dataparser_transform(c2w, dp_transform)

    # 构建 nerfstudio Cameras 对象
    # c2w: 3×4 矩阵
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
        # splatfacto 使用 get_outputs_for_camera（Gaussian Rasterization），
        # 不是 get_outputs_for_camera_ray_bundle（NeRF ray marching）
        outputs = pipeline.model.get_outputs_for_camera(camera)

    rgb = outputs["rgb"].detach().cpu().numpy()   # HxWx3 float [0,1]
    img = (rgb * 255).clip(0, 255).astype(np.uint8)
    return img


def make_grid_frame(
    cam_images: dict[str, Optional[np.ndarray]],
    grid_layout: list[list[str]],
    cell_w: int, cell_h: int, label_h: int,
) -> np.ndarray:
    """将多路图像拼成网格，每格上方加相机名标签。"""
    rows = []
    for row_cams in grid_layout:
        row_cells = []
        for cam_id in row_cams:
            img = cam_images.get(cam_id)
            cell_total_h = cell_h + label_h
            cell_canvas = np.zeros((cell_total_h, cell_w, 3), dtype=np.uint8)

            # 标签背景（深灰色）
            cell_canvas[:label_h, :] = (40, 40, 40)
            cv2.putText(
                cell_canvas, cam_id,
                (8, label_h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA,
            )

            if img is not None:
                # resize 到 cell_w × cell_h
                img_resized = cv2.resize(img, (cell_w, cell_h))
                cell_canvas[label_h:, :] = img_resized
            else:
                # 无图像时显示黑底红字
                cv2.putText(
                    cell_canvas, "N/A",
                    (cell_w // 2 - 20, label_h + cell_h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 200), 2,
                )

            row_cells.append(cell_canvas)
        rows.append(np.hstack(row_cells))
    return np.vstack(rows)


def main():
    parser = argparse.ArgumentParser(description="渲染 3DGS 多路摄像头视频")
    parser.add_argument("--checkpoint", required=True,
                        help="nerfstudio checkpoint 目录（包含 scene-0061_s0 子目录）")
    parser.add_argument("--mcap", required=True,
                        help="原始 MCAP 文件路径")
    parser.add_argument("--scene-data", required=True,
                        help="nerfstudio 训练数据目录（含 transforms.json）")
    parser.add_argument("--output", required=True,
                        help="输出 MP4 文件路径")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="最多渲染帧数（调试用，None 表示全部）")
    args = parser.parse_args()

    # 1. 找到 checkpoint
    ckpt_path = find_latest_checkpoint(args.checkpoint)
    if ckpt_path is None:
        print(f"[错误] 在 {args.checkpoint} 下找不到 nerfstudio_models/，请确认训练已完成。")
        sys.exit(1)
    print(f"[渲染] 使用 checkpoint: {ckpt_path}")

    # 2. 加载模型
    print("[渲染] 加载 splatfacto 模型 ...")
    pipeline = load_splatfacto_model(ckpt_path)
    print(f"[渲染] 模型加载完成，device: {pipeline.device}")

    # 2b. 加载 dataparser_transforms.json（训练时的坐标归一化参数）
    dp_transforms_path = ckpt_path.parent / "dataparser_transforms.json"
    if not dp_transforms_path.exists():
        print(f"[警告] 找不到 dataparser_transforms.json，渲染坐标可能不正确！")
        dp_transform = None
    else:
        with open(dp_transforms_path) as f:
            dp_transform = json.load(f)
        T = dp_transform["transform"]
        scale = dp_transform["scale"]
        print(f"[渲染] dataparser_transforms: 平移={[round(T[i][3],3) for i in range(3)]}, scale={scale:.5f}")

    # 3. 读取 transforms.json，按 camera_id 分组位姿
    scene_data_dir = Path(args.scene_data)
    with open(scene_data_dir / "transforms.json") as f:
        transforms = json.load(f)

    # 收集每路相机的 (frame_idx, c2w, intrinsics)
    cam_frames: dict[str, list[dict]] = {}
    for frame in transforms["frames"]:
        cam_id = frame.get("camera_id", "UNKNOWN")
        if cam_id not in cam_frames:
            cam_frames[cam_id] = []
        cam_frames[cam_id].append(frame)

    print(f"[渲染] 相机路数: {len(cam_frames)}, 各路帧数: { {k: len(v) for k, v in cam_frames.items()} }")

    # 4. 决定总帧数（取各路最小帧数）
    n_frames = min(len(v) for v in cam_frames.values())
    if args.max_frames:
        n_frames = min(n_frames, args.max_frames)
    print(f"[渲染] 将渲染 {n_frames} 帧 × {len(cam_frames)} 路")

    # 5. 初始化视频写入器
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grid_w = CELL_W * len(CAM_GRID[0])
    grid_h = (CELL_H + LABEL_H) * len(CAM_GRID)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, FPS, (grid_w, grid_h))

    # 6. 逐帧渲染
    for frame_i in range(n_frames):
        if frame_i % 20 == 0:
            print(f"[渲染] {frame_i}/{n_frames} ({frame_i/n_frames*100:.0f}%) ...")

        cam_images: dict[str, Optional[np.ndarray]] = {}
        for cam_id in [c for row in CAM_GRID for c in row]:
            frames_for_cam = cam_frames.get(cam_id)
            if frames_for_cam is None or frame_i >= len(frames_for_cam):
                cam_images[cam_id] = None
                continue

            fr = frames_for_cam[frame_i]
            c2w_list = fr["transform_matrix"]
            c2w = np.array(c2w_list, dtype=np.float32)  # 4×4

            fx = fr.get("fl_x", transforms["fl_x"])
            fy = fr.get("fl_y", transforms["fl_y"])
            cx_val = fr.get("cx", transforms["cx"])
            cy_val = fr.get("cy", transforms["cy"])
            W = fr.get("w", transforms["w"])
            H = fr.get("h", transforms["h"])

            try:
                img = render_frame_from_pipeline(
                    pipeline, c2w,
                    fx, fy, cx_val, cy_val,
                    W, H,
                    dp_transform=dp_transform,
                )
                cam_images[cam_id] = img
            except Exception as e:
                print(f"  [警告] {cam_id} 帧 {frame_i} 渲染失败: {e}")
                cam_images[cam_id] = None

        grid = make_grid_frame(cam_images, CAM_GRID, CELL_W, CELL_H, LABEL_H)
        # OpenCV 使用 BGR，渲染输出为 RGB
        writer.write(cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))

    writer.release()
    print(f"[渲染] 视频已保存：{out_path}  ({n_frames} 帧 @ {FPS}fps)")


if __name__ == "__main__":
    main()
