#!/usr/bin/env python3
"""extract_lidar_pointcloud.py — 从 MCAP 提取点云，并剔除 3D Box 内的点。

用法：
  python scripts/extract_lidar_pointcloud.py \\
    --mcap data/input/NuScenes-v1.0-mini-scene-0061.mcap \\
    --scene-data data/scenes/scene-0061_s0_v5 \\
    --checkpoint ... \\
    --output ... \\
    --voxel-size 1.0 \\
    --filter-dynamic  <-- 新增
"""
import argparse
import json
import math
import struct
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation as R
from mcap.reader import make_reader
from mcap_protobuf.decoder import DecoderFactory

# --------------------------------------------------------------------------
# 3D Box 辅助
# --------------------------------------------------------------------------

def load_annotations(mcap_path):
    """加载所有 /markers/annotations 消息，按时间戳排序。"""
    msgs = []
    with open(mcap_path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        for sch, ch, msg, proto in reader.iter_decoded_messages(topics=['/markers/annotations']):
            msgs.append((msg.log_time, proto.entities))
    msgs.sort(key=lambda x: x[0])
    return msgs

def find_nearest_entities(annotations, ts):
    if not annotations: return []
    # 二分查找
    import bisect
    times = [x[0] for x in annotations]
    idx = bisect.bisect_left(times, ts)
    if idx == 0: best_idx = 0
    elif idx == len(times): best_idx = -1
    else:
        # 比较 idx 和 idx-1
        if abs(times[idx] - ts) < abs(times[idx-1] - ts):
            best_idx = idx
        else:
            best_idx = idx - 1
            
    if abs(times[best_idx] - ts) > 0.5 * 1e9: return []
    return annotations[best_idx][1]

def is_point_in_box(point, size, pose):
    """判断点是否在 Oriented Box 内。"""
    # 1. 变换到 Box 局部坐标
    # world -> local: R^T * (p - t)
    pos = np.array([pose.position.x, pose.position.y, pose.position.z])
    quat = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
    r = R.from_quat(quat)
    
    # 向量差
    diff = point - pos
    # 逆旋转
    local_p = r.inv().apply(diff)
    
    # 2. AABB 检查
    dx, dy, dz = size.x / 2, size.y / 2, size.z / 2
    # 稍微放大 Box (0.2m) 以确保剔除干净
    margin = 0.2
    return (abs(local_p[0]) <= dx + margin) and \
           (abs(local_p[1]) <= dy + margin) and \
           (abs(local_p[2]) <= dz + margin)

# --------------------------------------------------------------------------
# 原有辅助函数
# --------------------------------------------------------------------------

def quat_to_rot3(x, y, z, w):
    x2, y2, z2 = x*x, y*y, z*z
    xy, xz, yz = x*y, x*z, y*z
    wx, wy, wz = w*x, w*y, w*z
    return np.array([
        [1-2*(y2+z2), 2*(xy-wz),   2*(xz+wy)  ],
        [2*(xy+wz),   1-2*(x2+z2), 2*(yz-wx)  ],
        [2*(xz-wy),   2*(yz+wx),   1-2*(x2+y2)],
    ])

def make_T44(rot3, tx, ty, tz):
    T = np.eye(4)
    T[:3, :3] = rot3
    T[:3, 3] = [tx, ty, tz]
    return T

def slerp_quat(q0, q1, t):
    x0, y0, z0, w0 = q0
    x1, y1, z1, w1 = q1
    dot = x0*x1 + y0*y1 + z0*z1 + w0*w1
    if dot < 0:
        x1, y1, z1, w1 = -x1, -y1, -z1, -w1
        dot = -dot
    if dot > 0.9995:
        rx, ry, rz, rw = x0+t*(x1-x0), y0+t*(y1-y0), z0+t*(z1-z0), w0+t*(w1-w0)
    else:
        th0 = math.acos(min(dot, 1.0))
        th = th0 * t
        s0 = math.cos(th) - dot * math.sin(th) / math.sin(th0)
        s1 = math.sin(th) / math.sin(th0)
        rx, ry, rz, rw = s0*x0+s1*x1, s0*y0+s1*y1, s0*z0+s1*z1, s0*w0+s1*w1
    n = math.sqrt(rx*rx + ry*ry + rz*rz + rw*rw)
    return rx/n, ry/n, rz/n, rw/n

def load_tf_data(mcap_path: str):
    ego_list = []
    lidar_T = None
    with open(mcap_path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        for _sch, _ch, msg, proto in reader.iter_decoded_messages(topics=["/tf"]):
            parent = proto.parent_frame_id
            child  = proto.child_frame_id
            tx, ty, tz = proto.translation.x, proto.translation.y, proto.translation.z
            qx, qy, qz, qw = proto.rotation.x, proto.rotation.y, proto.rotation.z, proto.rotation.w
            rot3 = quat_to_rot3(qx, qy, qz, qw)
            T = make_T44(rot3, tx, ty, tz)
            if parent == "map" and child == "base_link":
                ego_list.append((msg.log_time, T))
            elif parent == "base_link" and child == "LIDAR_TOP" and lidar_T is None:
                lidar_T = T
    ego_list.sort(key=lambda x: x[0])
    return ego_list, lidar_T

def interpolate_ego(ego_list, ts_ns):
    if ts_ns <= ego_list[0][0]: return ego_list[0][1]
    if ts_ns >= ego_list[-1][0]: return ego_list[-1][1]
    import bisect
    times = [x[0] for x in ego_list]
    idx = bisect.bisect_left(times, ts_ns)
    t0, m0 = ego_list[idx-1]
    t1, m1 = ego_list[idx]
    alpha = (ts_ns - t0) / (t1 - t0)
    pos = m0[:3, 3] + alpha * (m1[:3, 3] - m0[:3, 3])
    def mat_to_quat(m):
        return R.from_matrix(m[:3,:3]).as_quat() # (x,y,z,w)
    q0 = mat_to_quat(m0); q1 = mat_to_quat(m1)
    # scipy slerp
    key_rots = R.from_quat([q0, q1])
    key_times = [0, 1]
    slerp = \
        R.from_quat(slerp_quat((q0[0],q0[1],q0[2],q0[3]), (q1[0],q1[1],q1[2],q1[3]), alpha))
        
    T = np.eye(4); T[:3,:3] = slerp.as_matrix(); T[:3,3] = pos
    return T

def parse_lidar_frame(proto) -> np.ndarray:
    stride = proto.point_stride
    data = proto.data
    n_pts = len(data) // stride
    pts = np.frombuffer(data, dtype=np.float32).reshape(n_pts, stride // 4)
    return pts[:, :3]

def _write_ply_binary(path: Path, pts: np.ndarray) -> None:
    n = len(pts)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    ).encode()
    xyz = pts.astype(np.float32)
    rgb = np.full((n, 3), 128, dtype=np.uint8)
    vertex_data = np.zeros(n, dtype=[('x','f4'),('y','f4'),('z','f4'),
                                      ('r','u1'),('g','u1'),('b','u1')])
    vertex_data['x'] = xyz[:,0]; vertex_data['y'] = xyz[:,1]; vertex_data['z'] = xyz[:,2]
    vertex_data['r'] = rgb[:,0]; vertex_data['g'] = rgb[:,1]; vertex_data['b'] = rgb[:,2]
    with open(path, "wb") as f:
        f.write(header)
        f.write(vertex_data.tobytes())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcap",       required=True)
    parser.add_argument("--scene-data", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output",     required=True)
    parser.add_argument("--voxel-size", type=float, default=0.1)
    parser.add_argument("--filter-dynamic", action="store_true", help="剔除 Box 内的点")
    args = parser.parse_args()

    print("[LiDAR] 加载 /tf 位姿数据 ...")
    ego_list, lidar_extrinsic = load_tf_data(args.mcap)
    
    annotations = []
    if args.filter_dynamic:
        print("[LiDAR] 加载动态物体标注 ...")
        annotations = load_annotations(args.mcap)

    print("[LiDAR] 读取并变换 LiDAR 帧 ...")
    all_world_pts = []
    frame_count = 0

    with open(args.mcap, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        for _sch, _ch, msg, proto in reader.iter_decoded_messages(topics=["/LIDAR_TOP"]):
            ts_ns = msg.log_time
            world_T_veh = interpolate_ego(ego_list, ts_ns)
            world_T_lidar = world_T_veh @ lidar_extrinsic
            pts_sensor = parse_lidar_frame(proto)
            
            # 基础过滤
            dist = np.linalg.norm(pts_sensor, axis=1)
            valid = (dist > 0.5) & (dist < 80.0) & np.isfinite(pts_sensor).all(axis=1)
            pts_sensor = pts_sensor[valid]
            
            # 变换到世界坐标
            pts_h = np.hstack([pts_sensor, np.ones((len(pts_sensor), 1))])
            pts_world = (world_T_lidar @ pts_h.T).T[:, :3]
            
            # 动态物体过滤
            if args.filter_dynamic and annotations:
                entities = find_nearest_entities(annotations, ts_ns)
                if entities:
                    # 找出所有在 Box 内的点
                    # 为性能，这里只做简单的 Python 循环，可能会慢
                    # 优化：批量过滤
                    # 实际上车辆并不多，每帧 ~20 个 box
                    keep_mask = np.ones(len(pts_world), dtype=bool)
                    for ent in entities:
                        if not ent.cubes: continue
                        cube = ent.cubes[0]
                        # 检查 box 范围内的点
                        # 先用中心距离粗筛
                        pos = np.array([cube.pose.position.x, cube.pose.position.y, cube.pose.position.z])
                        radius = max(cube.size.x, cube.size.y)
                        
                        dists = np.linalg.norm(pts_world - pos, axis=1)
                        candidates = dists < radius + 0.5
                        
                        if not np.any(candidates): continue
                        
                        # 精细检查
                        # 转换 candidates 到局部坐标
                        cand_indices = np.where(candidates)[0]
                        cand_pts = pts_world[cand_indices]
                        
                        quat = [cube.pose.orientation.x, cube.pose.orientation.y, cube.pose.orientation.z, cube.pose.orientation.w]
                        r = R.from_quat(quat)
                        local_pts = r.inv().apply(cand_pts - pos)
                        
                        dx, dy, dz = cube.size.x/2+0.2, cube.size.y/2+0.2, cube.size.z/2+0.2
                        in_box = (np.abs(local_pts[:,0]) <= dx) & (np.abs(local_pts[:,1]) <= dy) & (np.abs(local_pts[:,2]) <= dz)
                        
                        # 标记删除
                        keep_mask[cand_indices[in_box]] = False
                        
                    pts_world = pts_world[keep_mask]

            all_world_pts.append(pts_world)
            frame_count += 1
            if frame_count % 50 == 0:
                print(f"  处理 {frame_count} 帧, 点数: {sum(len(p) for p in all_world_pts):,}")

    all_pts = np.vstack(all_world_pts)
    print(f"[LiDAR] 原始总点数: {len(all_pts):,}")

    # 降采样
    if args.voxel_size > 0:
        print(f"[LiDAR] 降采样 voxel={args.voxel_size} ...")
        voxel_indices = np.floor(all_pts / args.voxel_size).astype(np.int64)
        _, unique_idx = np.unique(voxel_indices, axis=0, return_index=True)
        all_pts = all_pts[unique_idx]
        print(f"  剩余: {len(all_pts):,}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_ply_binary(out_path, all_pts)
    print(f"[LiDAR] 已保存: {out_path}")
    
    # 更新 transforms.json
    with open(Path(args.scene_data) / "transforms.json", "r+") as f:
        data = json.load(f)
        data["ply_file_path"] = str(out_path.relative_to(args.scene_data))
        f.seek(0); json.dump(data, f, indent=2); f.truncate()

if __name__ == "__main__":
    main()
