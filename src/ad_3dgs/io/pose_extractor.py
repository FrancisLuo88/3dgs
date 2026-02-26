"""PoseExtractor — 从 MCAP 的 /tf channel 提取相机在世界坐标系中的位姿。

数据来源：
  - /tf  map→base_link    : 动态 ego 位姿（~130 Hz，2534 条/scene）
  - /tf  base_link→CAM_*  : 静态 sensor 外参（39 条/scene，实为同一值重复）

计算链：
  world_T_cam = world_T_vehicle(插值) @ vehicle_T_cam(静态)

坐标系：nuScenes 使用右手系，相机坐标系 x右/y下/z前（OpenCV 约定），
        nerfstudio splatfacto 期望相同约定，无需额外转换。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from ad_3dgs.types import CameraPose, Timeline


# 4×4 矩阵以 list[float]（16 个元素，行优先）表示
Matrix4x4 = list[float]


# ---------------------------------------------------------------------------
# 辅助函数：四元数 → 旋转矩阵
# ---------------------------------------------------------------------------

def _quat_to_rot3(x: float, y: float, z: float, w: float) -> list[list[float]]:
    """单位四元数 (x,y,z,w) → 3×3 旋转矩阵（列表格式）。"""
    x2, y2, z2 = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        [1 - 2*(y2+z2),   2*(xy-wz),     2*(xz+wy)   ],
        [2*(xy+wz),        1 - 2*(x2+z2), 2*(yz-wx)   ],
        [2*(xz-wy),        2*(yz+wx),     1 - 2*(x2+y2)],
    ]


def _make_transform(
    rot3: list[list[float]],
    tx: float, ty: float, tz: float,
) -> Matrix4x4:
    """将 3×3 旋转矩阵和平移向量组合为行优先 4×4 齐次变换矩阵。"""
    r = rot3
    return [
        r[0][0], r[0][1], r[0][2], tx,
        r[1][0], r[1][1], r[1][2], ty,
        r[2][0], r[2][1], r[2][2], tz,
        0.0,     0.0,     0.0,     1.0,
    ]


def _mat4_mul(A: Matrix4x4, B: Matrix4x4) -> Matrix4x4:
    """行优先 4×4 矩阵乘法：C = A @ B。"""
    C = [0.0] * 16
    for i in range(4):
        for j in range(4):
            s = 0.0
            for k in range(4):
                s += A[i*4+k] * B[k*4+j]
            C[i*4+j] = s
    return C


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _slerp_quat(
    q0: tuple[float, float, float, float],
    q1: tuple[float, float, float, float],
    t: float,
) -> tuple[float, float, float, float]:
    """球面线性插值（SLERP）两个四元数 (x,y,z,w)。"""
    x0, y0, z0, w0 = q0
    x1, y1, z1, w1 = q1

    dot = x0*x1 + y0*y1 + z0*z1 + w0*w1
    if dot < 0.0:
        x1, y1, z1, w1 = -x1, -y1, -z1, -w1
        dot = -dot

    if dot > 0.9995:
        # 近乎平行，线性近似
        rx = x0 + t*(x1-x0)
        ry = y0 + t*(y1-y0)
        rz = z0 + t*(z1-z0)
        rw = w0 + t*(w1-w0)
    else:
        theta0 = math.acos(min(dot, 1.0))
        theta = theta0 * t
        sin0 = math.sin(theta0)
        s0 = math.cos(theta) - dot * math.sin(theta) / sin0
        s1 = math.sin(theta) / sin0
        rx = s0*x0 + s1*x1
        ry = s0*y0 + s1*y1
        rz = s0*z0 + s1*z1
        rw = s0*w0 + s1*w1

    norm = math.sqrt(rx*rx + ry*ry + rz*rz + rw*rw)
    return (rx/norm, ry/norm, rz/norm, rw/norm)


# ---------------------------------------------------------------------------
# PoseExtractor
# ---------------------------------------------------------------------------

class PoseExtractor:
    """从 MCAP 的 /tf channel 提取 Timeline 对应的每帧相机位姿。

    Args:
        mcap_path: 输入 MCAP 文件路径。
    """

    def __init__(self, mcap_path: str | Path) -> None:
        self._mcap_path = Path(mcap_path)

        # 缓存
        # ego poses: list of (timestamp_ns, world_T_vehicle: Matrix4x4)，按时间升序
        self._ego_poses: Optional[list[tuple[int, Matrix4x4]]] = None
        # 静态外参: camera_id -> vehicle_T_cam: Matrix4x4
        self._vehicle_T_cam: Optional[dict[str, Matrix4x4]] = None

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def extract(self, timeline: Timeline) -> dict[str, list[CameraPose]]:
        """提取 timeline 中所有 entry 的相机位姿。

        Returns:
            camera_id -> list[CameraPose]，顺序与 timeline.entries 一一对应。
            若某 entry 的某路相机无法插值（时间戳超出 ego 位姿范围），跳过该路。
        """
        self._load_tf()

        result: dict[str, list[CameraPose]] = {
            cam_id: [] for cam_id in self._vehicle_T_cam
        }

        for entry in timeline.entries:
            world_T_veh = self._interpolate_ego_pose(entry.timestamp_ns)
            if world_T_veh is None:
                # 时间戳超出 ego 位姿覆盖范围，各路补空
                for cam_id in result:
                    result[cam_id].append(
                        CameraPose(camera_id=cam_id, timestamp_ns=entry.timestamp_ns, transform=[0.0]*16)
                    )
                continue

            for cam_id, veh_T_cam in self._vehicle_T_cam.items():
                world_T_cam = _mat4_mul(world_T_veh, veh_T_cam)
                result[cam_id].append(
                    CameraPose(
                        camera_id=cam_id,
                        timestamp_ns=entry.timestamp_ns,
                        transform=world_T_cam,
                    )
                )

        return result

    def get_static_extrinsics(self) -> dict[str, Matrix4x4]:
        """返回各相机的静态外参 vehicle_T_cam（4×4 行优先）。"""
        self._load_tf()
        return dict(self._vehicle_T_cam)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_tf(self) -> None:
        """扫描 /tf channel，填充 self._ego_poses 和 self._vehicle_T_cam。"""
        if self._ego_poses is not None:
            return

        from mcap.reader import make_reader
        from mcap_protobuf.decoder import DecoderFactory

        ego_list: list[tuple[int, Matrix4x4]] = []
        # camera_id -> (translation, rotation) 取第一次出现的静态值
        static_raw: dict[str, tuple] = {}

        decoder = DecoderFactory()
        with open(self._mcap_path, "rb") as f:
            reader = make_reader(f, decoder_factories=[decoder])
            for _sch, _ch, msg, proto in reader.iter_decoded_messages(topics=["/tf"]):
                parent = proto.parent_frame_id
                child = proto.child_frame_id

                tx = proto.translation.x
                ty = proto.translation.y
                tz = proto.translation.z
                qx = proto.rotation.x
                qy = proto.rotation.y
                qz = proto.rotation.z
                qw = proto.rotation.w

                if parent == "map" and child == "base_link":
                    rot3 = _quat_to_rot3(qx, qy, qz, qw)
                    mat = _make_transform(rot3, tx, ty, tz)
                    ego_list.append((msg.log_time, mat))

                elif parent == "base_link" and child.startswith("CAM_"):
                    if child not in static_raw:
                        static_raw[child] = (tx, ty, tz, qx, qy, qz, qw)

        ego_list.sort(key=lambda x: x[0])
        self._ego_poses = ego_list

        # 构建静态外参矩阵
        self._vehicle_T_cam = {}
        for cam_id, (tx, ty, tz, qx, qy, qz, qw) in static_raw.items():
            rot3 = _quat_to_rot3(qx, qy, qz, qw)
            self._vehicle_T_cam[cam_id] = _make_transform(rot3, tx, ty, tz)

    def _interpolate_ego_pose(self, timestamp_ns: int) -> Optional[Matrix4x4]:
        """在 ego_poses 序列中插值出 timestamp_ns 时刻的 world_T_vehicle。

        使用线性插值位置 + SLERP 插值旋转。
        若 timestamp_ns 超出范围，返回最近端（clamp）。
        """
        poses = self._ego_poses
        if not poses:
            return None

        # 边界处理：clamp 到首尾
        if timestamp_ns <= poses[0][0]:
            return poses[0][1]
        if timestamp_ns >= poses[-1][0]:
            return poses[-1][1]

        # 二分查找插值区间
        lo, hi = 0, len(poses) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if poses[mid][0] <= timestamp_ns:
                lo = mid
            else:
                hi = mid

        t0, m0 = poses[lo]
        t1, m1 = poses[hi]
        alpha = (timestamp_ns - t0) / (t1 - t0)

        # 插值位置（矩阵第 4 列前三行）
        tx = _lerp(m0[3],  m1[3],  alpha)
        ty = _lerp(m0[7],  m1[7],  alpha)
        tz = _lerp(m0[11], m1[11], alpha)

        # 从矩阵提取四元数再 SLERP（避免直接插值旋转矩阵的正交性损失）
        q0 = _rot3_to_quat(m0)
        q1 = _rot3_to_quat(m1)
        qx, qy, qz, qw = _slerp_quat(q0, q1, alpha)
        rot3 = _quat_to_rot3(qx, qy, qz, qw)
        return _make_transform(rot3, tx, ty, tz)


def _rot3_to_quat(
    m: Matrix4x4,
) -> tuple[float, float, float, float]:
    """从行优先 4×4 矩阵的左上 3×3 提取四元数 (x,y,z,w)。

    使用 Shepperd 方法，数值稳定。
    """
    r00, r01, r02 = m[0], m[1], m[2]
    r10, r11, r12 = m[4], m[5], m[6]
    r20, r21, r22 = m[8], m[9], m[10]
    trace = r00 + r11 + r22

    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (r21 - r12) * s
        y = (r02 - r20) * s
        z = (r10 - r01) * s
    elif r00 > r11 and r00 > r22:
        s = 2.0 * math.sqrt(1.0 + r00 - r11 - r22)
        w = (r21 - r12) / s
        x = 0.25 * s
        y = (r01 + r10) / s
        z = (r02 + r20) / s
    elif r11 > r22:
        s = 2.0 * math.sqrt(1.0 + r11 - r00 - r22)
        w = (r02 - r20) / s
        x = (r01 + r10) / s
        y = 0.25 * s
        z = (r12 + r21) / s
    else:
        s = 2.0 * math.sqrt(1.0 + r22 - r00 - r11)
        w = (r10 - r01) / s
        x = (r02 + r20) / s
        y = (r12 + r21) / s
        z = 0.25 * s

    norm = math.sqrt(x*x + y*y + z*z + w*w)
    return (x/norm, y/norm, z/norm, w/norm)
