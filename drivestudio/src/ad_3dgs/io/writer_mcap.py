"""LogWriterMcap — ILogWriter 的 MCAP 主实现。

将合成后的多路图像按 Timeline 时间戳写回 Foxglove protobuf MCAP，
格式与 nuscenes2mcap 输出一致，可在 Foxglove Studio 中回放。
依赖：mcap>=1.3.0, mcap-protobuf-support>=0.5.1, protobuf>=4.25
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import google.protobuf.descriptor_pb2 as _desc_pb2
import google.protobuf.descriptor_pool as _desc_pool
from google.protobuf import message_factory as _msg_factory
from mcap.reader import make_reader
from mcap.writer import Writer

from ad_3dgs.io.writer import ILogWriter
from ad_3dgs.types import CameraInfo, CompositeFrame

# topic suffix 约定（与 reader_mcap.py 一致）
_IMAGE_SUFFIX = "/image_rect_compressed"
_CALIBRATION_SUFFIX = "/camera_info"


def _load_proto_class(schema_data: bytes, class_name: str):
    """从 FileDescriptorSet 字节动态加载 protobuf 消息类。"""
    fds = _desc_pb2.FileDescriptorSet()
    fds.ParseFromString(schema_data)
    pool = _desc_pool.DescriptorPool()
    for fd in fds.file:
        pool.Add(fd)
    classes = _msg_factory.GetMessages([fds.file[-1]], pool=pool)
    return classes[class_name]


class LogWriterMcap(ILogWriter):
    """将合成帧写入 Foxglove protobuf MCAP 文件。

    使用方式：
        with LogWriterMcap(out_path, camera_infos, ref_mcap_path) as w:
            for entry in timeline.entries:
                frames = composite(entry)
                w.write_sync_point(entry.timestamp_ns, frames)

    Args:
        path:          输出 MCAP 文件路径（不存在时自动创建父目录）。
        camera_infos:  camera_id -> CameraInfo 映射（提供内参与 topic 名）。
        ref_mcap_path: 参考 MCAP（用于读取 schema bytes），默认从输入 MCAP 重用。
                       若为 None，则使用内置最小 schema。
    """

    def __init__(
        self,
        path: str | Path,
        camera_infos: Dict[str, CameraInfo],
        ref_mcap_path: Optional[str | Path] = None,
    ) -> None:
        self._path = Path(path)
        self._camera_infos = camera_infos
        self._ref_mcap_path = Path(ref_mcap_path) if ref_mcap_path else None

        self._file = None
        self._writer: Optional[Writer] = None

        # schema bytes（从 ref MCAP 或内置）
        self._img_schema_data: Optional[bytes] = None
        self._cal_schema_data: Optional[bytes] = None

        # 动态 proto 类
        self._CompressedImage = None
        self._CameraCalibration = None

        # channel_id 映射：topic -> channel_id
        self._img_channel_ids: Dict[str, int] = {}
        self._cal_channel_ids: Dict[str, int] = {}

        self._opened = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def open(self) -> None:
        if self._opened:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "wb")
        self._writer = Writer(self._file)
        self._writer.start(profile="", library="ad_3dgs/LogWriterMcap")

        # 加载 schema bytes
        self._load_schemas()

        # 注册 schema + channel
        img_schema_id = self._writer.register_schema(
            name="foxglove.CompressedImage",
            encoding="protobuf",
            data=self._img_schema_data,
        )
        cal_schema_id = self._writer.register_schema(
            name="foxglove.CameraCalibration",
            encoding="protobuf",
            data=self._cal_schema_data,
        )

        for camera_id, ci in self._camera_infos.items():
            img_topic = ci.topic  # e.g. /CAM_FRONT/image_rect_compressed
            cal_topic = img_topic.replace(_IMAGE_SUFFIX, _CALIBRATION_SUFFIX)

            self._img_channel_ids[camera_id] = self._writer.register_channel(
                topic=img_topic,
                message_encoding="protobuf",
                schema_id=img_schema_id,
            )
            self._cal_channel_ids[camera_id] = self._writer.register_channel(
                topic=cal_topic,
                message_encoding="protobuf",
                schema_id=cal_schema_id,
            )

        self._opened = True

    def close(self) -> None:
        if self._writer is not None:
            self._writer.finish()
            self._writer = None
        if self._file is not None:
            self._file.close()
            self._file = None
        self._opened = False

    # ------------------------------------------------------------------
    # 写入接口
    # ------------------------------------------------------------------

    def write_frame(
        self,
        timestamp_ns: int,
        camera_id: str,
        image_bytes: bytes,
        camera_info: CameraInfo,
    ) -> None:
        """写入单路单帧图像 + 对应 camera_info。"""
        assert self._opened, "请先调用 open()"

        # --- 写图像 ---
        img_ch_id = self._img_channel_ids[camera_id]
        img_proto = self._CompressedImage()
        img_proto.timestamp.seconds = timestamp_ns // 1_000_000_000
        img_proto.timestamp.nanos = timestamp_ns % 1_000_000_000
        img_proto.frame_id = camera_id
        img_proto.format = "jpeg"
        img_proto.data = image_bytes

        self._writer.add_message(
            channel_id=img_ch_id,
            log_time=timestamp_ns,
            data=img_proto.SerializeToString(),
            publish_time=timestamp_ns,
        )

        # --- 写标定 ---
        cal_ch_id = self._cal_channel_ids[camera_id]
        cal_proto = self._CameraCalibration()
        cal_proto.timestamp.seconds = timestamp_ns // 1_000_000_000
        cal_proto.timestamp.nanos = timestamp_ns % 1_000_000_000
        cal_proto.frame_id = camera_id
        cal_proto.width = camera_info.width
        cal_proto.height = camera_info.height
        cal_proto.distortion_model = camera_info.distortion_model
        cal_proto.K.extend(camera_info.K)
        cal_proto.D.extend(camera_info.D)
        cal_proto.R.extend(camera_info.R)
        cal_proto.P.extend(camera_info.P)

        self._writer.add_message(
            channel_id=cal_ch_id,
            log_time=timestamp_ns,
            data=cal_proto.SerializeToString(),
            publish_time=timestamp_ns,
        )

    def write_sync_point(
        self,
        timestamp_ns: int,
        frames: Dict[str, CompositeFrame],
    ) -> None:
        """写入一个同步时刻的全部多路帧，所有帧使用相同 timestamp_ns。"""
        for camera_id, composite in frames.items():
            ci = self._camera_infos.get(camera_id)
            if ci is None:
                raise KeyError(f"未注册的 camera_id：{camera_id}，请在构造时传入 camera_infos")
            self.write_frame(timestamp_ns, camera_id, composite.image_data, ci)

    def get_camera_topics(self) -> List[str]:
        return [ci.topic for ci in self._camera_infos.values()]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_schemas(self) -> None:
        """从参考 MCAP 读取 schema bytes，并动态加载 proto 类。"""
        if self._ref_mcap_path and self._ref_mcap_path.exists():
            with open(self._ref_mcap_path, "rb") as f:
                reader = make_reader(f)
                summary = reader.get_summary()
            for sc in summary.schemas.values():
                if sc.name == "foxglove.CompressedImage":
                    self._img_schema_data = sc.data
                elif sc.name == "foxglove.CameraCalibration":
                    self._cal_schema_data = sc.data

        # 若未能从参考 MCAP 读取，使用空 schema（测试 / 备用）
        if not self._img_schema_data:
            self._img_schema_data = b""
        if not self._cal_schema_data:
            self._cal_schema_data = b""

        # 动态加载 proto 类（需要非空 schema）
        if self._img_schema_data:
            self._CompressedImage = _load_proto_class(
                self._img_schema_data, "foxglove.CompressedImage"
            )
        if self._cal_schema_data:
            self._CameraCalibration = _load_proto_class(
                self._cal_schema_data, "foxglove.CameraCalibration"
            )

        if self._CompressedImage is None or self._CameraCalibration is None:
            raise RuntimeError(
                "无法加载 foxglove protobuf schema，请通过 ref_mcap_path 提供参考 MCAP 文件"
            )
