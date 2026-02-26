"""
核心数据类型：贯穿整个 pipeline 的内部数据结构。

层次关系：
  MCAP 文件
    └─ Timeline（时间戳索引，不含图像字节）
         └─ TimelineEntry（一个同步时刻）
              └─ FrameRef（单路相机的元数据引用）

  iter_frames() 按需从 MCAP seek 读取图像字节，返回 Frame
  IWeatherRenderer 输出 RenderedFrame
  IVirtualObjectInserter 输出 CompositeFrame
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 相机标定
# ---------------------------------------------------------------------------

@dataclass
class CameraInfo:
    """单路相机的内参与外参。

    内参来自 MCAP 中的 foxglove.CameraCalibration channel，
    外参（vehicle→camera 的旋转/平移）由 ILogReader 从 /tf 或 nuScenes
    元数据解析后附加。
    """
    camera_id: str              # 如 "CAM_FRONT"
    topic: str                  # 如 "/CAM_FRONT/image_rect_compressed"
    width: int                  # 图像宽度（像素）
    height: int                 # 图像高度（像素）

    # 内参矩阵（3×3，行优先展开为长度 9 的列表；与 foxglove.CameraCalibration.K 一致）
    K: list[float] = field(default_factory=lambda: [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0])

    # 畸变系数（nuScenes mini 中为空列表）
    D: list[float] = field(default_factory=list)
    distortion_model: str = ""

    # 投影矩阵（3×4，行优先展开为长度 12；与 foxglove.CameraCalibration.P 一致）
    P: list[float] = field(default_factory=lambda: [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0])

    # 修正矩阵（3×3；nuScenes 中为单位阵）
    R: list[float] = field(default_factory=lambda: [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0])

    # 外参：相机在车辆坐标系中的位姿（4×4 齐次变换矩阵，可选）
    # 仅在 Stage 2（3DGS 重建）中需要；从 nuScenes calibrated_sensor 解析
    extrinsic: Optional[list[float]] = None  # 16 个值，行优先；None 表示未加载

    @property
    def fx(self) -> float:
        return self.K[0]

    @property
    def fy(self) -> float:
        return self.K[4]

    @property
    def cx(self) -> float:
        return self.K[2]

    @property
    def cy(self) -> float:
        return self.K[5]


# ---------------------------------------------------------------------------
# Timeline（时间戳索引，不含图像字节）
# ---------------------------------------------------------------------------

@dataclass
class FrameRef:
    """单路相机单帧的元数据引用（不含图像字节）。

    log_offset 是 MCAP 文件中该消息体的字节偏移，
    由 mcap reader 的 message.data_start_offset 提供，
    供 iter_frames 按需 seek 读取，避免整包进内存。
    """
    topic: str
    timestamp_ns: int       # 纳秒 Unix 时间戳
    log_offset: int         # MCAP 文件字节偏移
    data_length: int        # 消息体字节长度


@dataclass
class TimelineEntry:
    """一个同步时刻：所有可用相机在该时刻的帧引用。

    timestamp_ns 为锚点时间戳（以 CAM_FRONT 为主锚）；
    frames 中不一定包含全部 6 路（某路偶尔缺帧时键缺失）。
    """
    timestamp_ns: int
    frames: dict[str, FrameRef] = field(default_factory=dict)  # topic -> FrameRef


@dataclass
class Timeline:
    """整段 MCAP 日志的时间戳序列。

    可序列化为 JSON 落盘供断点续传；格式见 docs/specs/timeline_format.md。
    """
    source_path: str                    # 原始 MCAP 文件绝对路径
    camera_topics: list[str]            # 6 路图像 topic 有序列表
    entries: list[TimelineEntry]        # 按 timestamp_ns 升序
    start_ns: int = 0
    end_ns: int = 0

    def __post_init__(self) -> None:
        if self.entries and not self.start_ns:
            self.start_ns = self.entries[0].timestamp_ns
        if self.entries and not self.end_ns:
            self.end_ns = self.entries[-1].timestamp_ns

    def slice(self, t_start: int, t_end: int) -> list[TimelineEntry]:
        """返回 [t_start, t_end] 范围内的 entries（均为纳秒）。"""
        return [e for e in self.entries if t_start <= e.timestamp_ns <= t_end]

    def __len__(self) -> int:
        return len(self.entries)

    # ------------------------------------------------------------------
    # 序列化（JSON 落盘，供断点续传）
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典（格式见 docs/specs/timeline_format.md）。"""
        return {
            "version": 1,
            "source_path": self.source_path,
            "camera_topics": self.camera_topics,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "entries": [
                {
                    "timestamp_ns": e.timestamp_ns,
                    "frames": {
                        topic: {
                            "topic": ref.topic,
                            "timestamp_ns": ref.timestamp_ns,
                            "log_offset": ref.log_offset,
                            "data_length": ref.data_length,
                        }
                        for topic, ref in e.frames.items()
                    },
                }
                for e in self.entries
            ],
        }

    def save(self, path: str | Path) -> None:
        """序列化为 JSON 写入文件。父目录不存在时自动创建。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "Timeline":
        """从字典反序列化，兼容 version=1。"""
        if d.get("version", 1) != 1:
            raise ValueError(f"不支持的 Timeline 格式版本：{d.get('version')}")

        entries = []
        for e in d["entries"]:
            frames = {
                topic: FrameRef(
                    topic=ref["topic"],
                    timestamp_ns=ref["timestamp_ns"],
                    log_offset=ref["log_offset"],
                    data_length=ref["data_length"],
                )
                for topic, ref in e["frames"].items()
            }
            entries.append(TimelineEntry(timestamp_ns=e["timestamp_ns"], frames=frames))

        return cls(
            source_path=d["source_path"],
            camera_topics=d["camera_topics"],
            entries=entries,
            start_ns=d.get("start_ns", 0),
            end_ns=d.get("end_ns", 0),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Timeline":
        """从 JSON 文件反序列化。"""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# 帧数据（含图像字节）
# ---------------------------------------------------------------------------

@dataclass
class Frame:
    """单路相机单帧：由 iter_frames 从 MCAP 解码后返回。

    image_data 为 JPEG 字节或解码后的 HxWxC uint8 numpy 数组，
    由 ILogReader 的实现决定（默认保持 JPEG bytes 以节省内存，
    需要 numpy array 时调用方自行解码）。
    """
    camera_id: str              # 如 "CAM_FRONT"
    topic: str                  # 如 "/CAM_FRONT/image_rect_compressed"
    timestamp_ns: int           # 纳秒时间戳
    image_data: bytes           # JPEG 字节（默认）或 numpy array（解码后）
    image_format: str = "jpeg"  # "jpeg" | "png" | "raw"
    width: int = 0
    height: int = 0


@dataclass
class MultiCameraFrame:
    """同一时刻 6 路相机帧的集合，由 iter_frames 以同步模式返回。"""
    timestamp_ns: int
    frames: dict[str, Frame] = field(default_factory=dict)  # camera_id -> Frame

    def __len__(self) -> int:
        return len(self.frames)

    def camera_ids(self) -> list[str]:
        return list(self.frames.keys())


# ---------------------------------------------------------------------------
# 渲染帧与合成帧
# ---------------------------------------------------------------------------

@dataclass
class RenderedFrame:
    """IWeatherRenderer 输出：单路相机单帧的重渲染结果。"""
    camera_id: str
    timestamp_ns: int
    image_data: bytes           # JPEG 字节或 numpy array
    image_format: str = "jpeg"
    weather_type: str = "rain_night"    # 当前渲染的天气类型
    width: int = 0
    height: int = 0


@dataclass
class CompositeFrame:
    """IVirtualObjectInserter 输出：植入虚拟物体后的合成帧。"""
    camera_id: str
    timestamp_ns: int
    image_data: bytes           # JPEG 字节或 numpy array
    image_format: str = "jpeg"
    object_ids: list[str] = field(default_factory=list)  # 该帧中已植入的虚拟物体 ID
    width: int = 0
    height: int = 0


# ---------------------------------------------------------------------------
# 虚拟物体
# ---------------------------------------------------------------------------

@dataclass
class VehicleSpec:
    """虚拟车辆的外观规格（资产描述）。"""
    vehicle_id: str             # 唯一标识
    model_path: str             # 3D 模型文件路径（如 .obj / .glb）
    length_m: float = 4.5       # 车长（米）
    width_m: float = 1.9        # 车宽（米）
    height_m: float = 1.5       # 车高（米）


@dataclass
class TrajectoryPoint:
    """轨迹上的单个位姿点。"""
    timestamp_ns: int
    x: float                    # 在世界坐标系中的位置（米）
    y: float
    z: float
    yaw: float                  # 航向角（弧度，绕 Z 轴）


@dataclass
class Trajectory:
    """虚拟物体的时间戳对齐轨迹。"""
    object_id: str
    points: list[TrajectoryPoint] = field(default_factory=list)


@dataclass
class CollisionVolume:
    """虚拟物体的碰撞体积（轴对齐包围盒，世界坐标系）。"""
    object_id: str
    timestamp_ns: int
    center_x: float
    center_y: float
    center_z: float
    half_length: float
    half_width: float
    half_height: float
    yaw: float


# ---------------------------------------------------------------------------
# Phase 2：3DGS 重建相关类型
# ---------------------------------------------------------------------------

@dataclass
class CameraPose:
    """单路相机单帧在世界坐标系中的位姿。

    transform 是 4×4 齐次变换矩阵 world_T_cam，行优先展开为 16 个 float。
    即：cam 坐标系中一点 p_cam，其世界坐标为 p_world = transform @ p_cam。
    坐标系约定：OpenCV（X 右, Y 下, Z 前），与 nerfstudio splatfacto 一致。
    """
    camera_id: str
    timestamp_ns: int
    transform: list[float]   # 16 个值，行优先（4×4 矩阵）


@dataclass
class SceneData:
    """一个 scene 的完整训练输入描述。

    由 SceneSplitter 将整段 Timeline 切分后生成；
    经 NerfstudioDataExporter 处理后在 output_dir 产出 images/ + transforms.json。
    """
    scene_id: str                        # 唯一标识，如 "scene-0061_s0"
    source_mcap: str                     # 原始 MCAP 文件绝对路径
    timeline: "Timeline"                 # 该 scene 的时间戳片段
    camera_infos: dict[str, "CameraInfo"] = field(default_factory=dict)  # camera_id -> CameraInfo
    output_dir: str = ""                 # 训练数据落盘目录（images/ + transforms.json）


@dataclass
class SceneHandle:
    """3DGS 训练结果引用（不存储模型权重本身，只存路径）。

    由 ISceneReconstructor.train() 返回；
    is_complete=False 表示中断，可通过 load_checkpoint 恢复训练。
    """
    scene_id: str
    checkpoint_dir: str                  # nerfstudio checkpoint 目录路径
    output_dir: str                      # 训练数据目录（含 transforms.json）
    is_complete: bool = False            # 是否训练完成
    last_step: int = 0                   # 最后完成的训练步数（0 表示未开始）
    render_output_dir: str = ""          # Phase 3 渲染输出目录（训练后填充）
