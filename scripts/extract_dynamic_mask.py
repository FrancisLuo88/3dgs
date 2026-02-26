#!/usr/bin/env python3
"""extract_dynamic_mask.py — 从 MCAP 提取动态物体 3D Box 并生成图像 Mask。

原理：
  1. 扫描 MCAP 建立 (camera_id, frame_idx) -> timestamp 映射
  2. 扫描 MCAP /markers/annotations 获取 3D Box (world frame)
  3. 遍历 transforms.json，找到对应时刻的 Box
  4. 将 Box 投影到图像，生成 Mask (白色=剔除区域)
  5. 更新 transforms.json 添加 mask_path

用法：
  python scripts/extract_dynamic_mask.py \\
    --mcap data/input/NuScenes-v1.0-mini-scene-0061.mcap \\
    --scene-data data/scenes/scene-0061_s0_v3
"""
import argparse
import json
import math
import re
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial.transform import Rotation as R
from mcap.reader import make_reader
from mcap_protobuf.decoder import DecoderFactory


def get_box_corners(size, pose):
    dx, dy, dz = size.x / 2, size.y / 2, size.z / 2
    corners_local = np.array([
        [-dx, -dy, -dz], [-dx, -dy,  dz],
        [-dx,  dy, -dz], [-dx,  dy,  dz],
        [ dx, -dy, -dz], [ dx, -dy,  dz],
        [ dx,  dy, -dz], [ dx,  dy,  dz],
    ])
    quat = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
    pos = [pose.position.x, pose.position.y, pose.position.z]
    r = R.from_quat(quat)
    rot_mat = r.as_matrix()
    return (rot_mat @ corners_local.T).T + pos


def project_box(corners_world, c2w, K, w, h):
    """投影 Box 8 点，返回凸包 Mask（若 Box 在视野内）。"""
    w2c = np.linalg.inv(c2w)
    pts_h = np.hstack([corners_world, np.ones((8, 1))])
    pts_cam = (w2c @ pts_h.T).T[:, :3]
    
    # 简单裁剪：如果所有点都在相机后方，忽略
    if np.all(pts_cam[:, 2] < 0.1):
        return None
        
    # 透视投影
    pts_img = (K @ pts_cam.T).T
    # 避免除零
    depth = pts_img[:, 2]
    depth[depth < 0.1] = 0.1
    pts_uv = pts_img[:, :2] / depth[:, None]
    
    pts_uv = pts_uv.astype(np.int32)
    return pts_uv


def load_image_timestamps(mcap_path):
    """建立 (cam_id, frame_idx) -> timestamp 映射。"""
    cam_counts = {} # cam_id -> count
    mapping = {}    # (cam_id, idx) -> ts
    
    with open(mcap_path, "rb") as f:
        reader = make_reader(f) # 不需要 decoder
        # 遍历原始消息（非常快）
        for schema, channel, message in reader.iter_messages():
            if schema.name == "foxglove.CompressedImage":
                # topic: /CAM_FRONT/image_rect_compressed
                parts = channel.topic.split('/')
                if len(parts) >= 2:
                    cam_id = parts[1]
                    idx = cam_counts.get(cam_id, 0)
                    mapping[(cam_id, idx)] = message.log_time
                    cam_counts[cam_id] = idx + 1
    return mapping


def load_annotations(mcap_path):
    """加载所有标注帧 (ts, entities)。"""
    msgs = []
    with open(mcap_path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        for sch, ch, msg, proto in reader.iter_decoded_messages(topics=['/markers/annotations']):
            msgs.append((msg.log_time, proto.entities))
    msgs.sort(key=lambda x: x[0])
    return msgs


def find_nearest_entities(annotations, ts):
    # 简单线性查找（数据量小）或二分
    # 既然是顺序处理，可以用游标优化，但这里简单起见直接找最近
    if not annotations: return []
    best = min(annotations, key=lambda x: abs(x[0] - ts))
    if abs(best[0] - ts) > 0.5 * 1e9: # 超过 0.5s 偏差认为无效
        return []
    return best[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcap", required=True)
    parser.add_argument("--scene-data", required=True)
    args = parser.parse_args()
    
    scene_dir = Path(args.scene_data)
    with open(scene_dir / "transforms.json") as f:
        tf = json.load(f)
        
    mask_dir = scene_dir / "masks"
    mask_dir.mkdir(exist_ok=True)
    
    print("[Mask] 扫描图像时间戳 ...")
    img_ts_map = load_image_timestamps(args.mcap)
    
    print("[Mask] 加载标注数据 ...")
    annotations = load_annotations(args.mcap)
    print(f"  共 {len(annotations)} 帧标注")
    
    frames = tf["frames"]
    updated_frames = []
    
    print(f"[Mask] 开始处理 {len(frames)} 帧图像 ...")
    
    # 解析文件名的正则
    # 假设: images/CAM_FRONT_frame_0000.jpg
    name_pattern = re.compile(r"images/(.+)_frame_(\d+)\.")
    
    cnt = 0
    for i, frame in enumerate(frames):
        fpath = frame["file_path"]
        m = name_pattern.match(fpath)
        if not m:
            print(f"[Warn] 无法解析文件名: {fpath}")
            updated_frames.append(frame)
            continue
            
        cam_id = m.group(1)
        frame_idx = int(m.group(2))
        
        # 1. 找时间戳
        ts = img_ts_map.get((cam_id, frame_idx))
        if ts is None:
            # 找不到时间戳，默认为无动态物体
            print(f"[Warn] 找不到时间戳: {cam_id} frame {frame_idx}，生成全黑 Mask")
            entities = []
        else:
            # 2. 找最近的 entities
            entities = find_nearest_entities(annotations, ts)
        
        # 3. 生成 Mask
        w = frame.get("w", tf["w"])
        h = frame.get("h", tf["h"])
        # 白色背景（保留），黑色前景（剔除）
        # Nerfstudio 约定: White (255) = Keep, Black (0) = Mask/Ignore
        mask_img = np.ones((h, w), dtype=np.uint8) * 255
        
        has_dynamic = False
        if entities:
            # 准备相机参数
            c2w = np.array(frame["transform_matrix"])
            fx = frame.get("fl_x", tf["fl_x"])
            fy = frame.get("fl_y", tf["fl_y"])
            cx = frame.get("cx", tf["cx"])
            cy = frame.get("cy", tf["cy"])
            K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
            
            for ent in entities:
                if hasattr(ent, 'cubes') and ent.cubes:
                    cube = ent.cubes[0]
                    corners = get_box_corners(cube.size, cube.pose)
                    pts_uv = project_box(corners, c2w, K, w, h)
                    
                    if pts_uv is not None:
                        hull = cv2.convexHull(pts_uv)
                        # 在 Mask 上绘制黑色多边形（0 表示剔除区域）
                        cv2.fillConvexPoly(mask_img, hull, 0)
                        has_dynamic = True
        
        # 膨胀 Mask 的黑色区域（即膨胀被剔除的物体区域，相当于腐蚀白色区域）
        if has_dynamic:
            kernel = np.ones((15, 15), np.uint8)
            mask_img = cv2.erode(mask_img, kernel, iterations=1)
        
        # 4. 保存 Mask（所有帧都要保存，即使是全黑）
        # 优化：如果是全黑且不强制生成文件，nerfstudio 可能会报错
        # 所以我们必须生成文件
        mask_filename = f"{cam_id}_mask_{frame_idx:04d}.png"
        mask_path = mask_dir / mask_filename
        cv2.imwrite(str(mask_path), mask_img)
        
        # 5. 更新 frame entry
        frame["mask_path"] = f"masks/{mask_filename}"
        updated_frames.append(frame)
        
        cnt += 1
        if cnt % 50 == 0:
            print(f"  已生成 {cnt} 个 mask")

    # 更新 transforms.json
    tf["frames"] = updated_frames
    with open(scene_dir / "transforms.json", "w") as f:
        json.dump(tf, f, indent=2)
        
    print(f"[Mask] 完成！已更新 transforms.json，Mask 保存在 {mask_dir}")

if __name__ == "__main__":
    main()
