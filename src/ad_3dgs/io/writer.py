"""输出层抽象接口：ILogWriter

支持 MCAP（主）与 ROS Bag（可选）两种实现。
职责：将合成后的多路图像按原 Timeline 时间戳严格对齐写回日志文件。
时间戳规则：所有 timestamp_ns 必须来自输入 Timeline，不允许重排或插值。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from ad_3dgs.types import CameraInfo, CompositeFrame


class ILogWriter(ABC):
    """多路相机日志写入器抽象基类。

    使用方式：
        with LogWriterMcap(path, topics, camera_infos) as writer:
            for entry in timeline.entries:
                frames = render_and_composite(entry)
                writer.write_sync_point(entry.timestamp_ns, frames)
    """

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ILogWriter":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    @abstractmethod
    def open(self) -> None:
        """创建输出文件，注册 schema 与 channel。"""

    @abstractmethod
    def close(self) -> None:
        """刷盘并关闭文件句柄。"""

    # ------------------------------------------------------------------
    # 写入接口
    # ------------------------------------------------------------------

    @abstractmethod
    def write_frame(
        self,
        timestamp_ns: int,
        camera_id: str,
        image_bytes: bytes,
        camera_info: CameraInfo,
    ) -> None:
        """写入单路单帧图像。

        Args:
            timestamp_ns: 纳秒时间戳，必须来自输入 Timeline。
            camera_id:    相机 ID，如 'CAM_FRONT'。
            image_bytes:  JPEG 编码的图像字节。
            camera_info:  对应的相机内参（同帧写入 camera_info channel）。
        """

    @abstractmethod
    def write_sync_point(
        self,
        timestamp_ns: int,
        frames: Dict[str, CompositeFrame],
    ) -> None:
        """一次写入一个同步时刻的全部多路帧。

        所有帧使用相同的 timestamp_ns，保证 6 路同步。

        Args:
            timestamp_ns: 该同步时刻的代表时间戳（纳秒）。
            frames:       camera_id -> CompositeFrame 映射。
        """

    def get_camera_topics(self) -> List[str]:
        """返回已注册的图像 topic 列表（可选实现）。"""
        return []
