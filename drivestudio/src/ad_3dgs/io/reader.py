"""输入层抽象接口：ILogReader

支持 MCAP（主）与 ROS Bag（可选）两种实现。
职责：从多路相机日志中按时间戳有序、流式读取，不将整包加载进内存。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, List

from ad_3dgs.types import CameraInfo, MultiCameraFrame, Timeline


class ILogReader(ABC):
    """多路相机日志读取器抽象基类。

    使用方式：
        with LogReaderMcap(path) as reader:
            timeline = reader.get_timeline()
            for frame in reader.iter_frames(timeline.start_ns, timeline.end_ns, reader.get_topic_names()):
                process(frame)
    """

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ILogReader":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @abstractmethod
    def open(self) -> None:
        """打开日志文件，初始化内部索引。"""

    @abstractmethod
    def close(self) -> None:
        """释放文件句柄与内部资源。"""

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    @abstractmethod
    def get_topic_names(self) -> List[str]:
        """返回所有相机图像 topic 名列表（有序）。

        MCAP 实现返回如 ['/CAM_FRONT/image_rect_compressed', ...] 共 6 项。
        """

    @abstractmethod
    def get_camera_info(self, topic_id: str) -> CameraInfo:
        """返回指定图像 topic 对应的相机内参。

        Args:
            topic_id: 图像 topic 名，如 '/CAM_FRONT/image_rect_compressed'。
        """

    @abstractmethod
    def get_timeline(self) -> Timeline:
        """扫描所有图像消息，构建并返回时间戳索引。

        返回的 Timeline 可调用 .save(path) 持久化供断点续传。
        该方法应在 open() 之后调用，结果可缓存（幂等）。
        """

    @abstractmethod
    def iter_frames(
        self,
        t_start: int,
        t_end: int,
        camera_topic_ids: List[str],
    ) -> Iterator[MultiCameraFrame]:
        """按时间区间流式迭代同步帧。

        Args:
            t_start: 起始时间戳（纳秒，含）。
            t_end:   结束时间戳（纳秒，含）。
            camera_topic_ids: 要读取的 topic 列表；传入 get_topic_names() 即读全部 6 路。

        Yields:
            MultiCameraFrame：一个同步时刻的多路帧集合，timestamp_ns 来自 Timeline。
        """
