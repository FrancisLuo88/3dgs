"""LogReaderMcap — ILogReader 的 MCAP 主实现。

读取 nuscenes2mcap 产出的 Foxglove protobuf MCAP 文件。
依赖：mcap>=1.3.0, mcap-protobuf-support>=0.5.1
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, List, Optional

from mcap.reader import make_reader
from mcap_protobuf.decoder import DecoderFactory

from ad_3dgs.io.reader import ILogReader
from ad_3dgs.types import (
    CameraInfo,
    Frame,
    FrameRef,
    MultiCameraFrame,
    Timeline,
    TimelineEntry,
)

# topic suffix -> camera_id mapping
_IMAGE_SUFFIX = "/image_rect_compressed"
_CALIBRATION_SUFFIX = "/camera_info"

# Canonical 6-camera ordering（与 nuScenes 惯例一致）
_CAMERA_ORDER = [
    "CAM_FRONT",
    "CAM_FRONT_LEFT",
    "CAM_FRONT_RIGHT",
    "CAM_BACK",
    "CAM_BACK_LEFT",
    "CAM_BACK_RIGHT",
]


class LogReaderMcap(ILogReader):
    """从 nuscenes2mcap 产出的 MCAP 文件流式读取 6 路相机数据。

    Args:
        path:            MCAP 文件路径。
        sync_window_ms:  构建 Timeline 时，其他路相机与锚点的最大时间差（毫秒），默认 50。
    """

    def __init__(self, path: str | Path, sync_window_ms: int = 50) -> None:
        self._path = Path(path)
        self._sync_window_ns = sync_window_ms * 1_000_000

        self._file = None
        self._reader = None
        self._summary = None

        # 缓存
        self._topic_names: Optional[List[str]] = None
        self._camera_infos: dict[str, CameraInfo] = {}
        self._timeline: Optional[Timeline] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def open(self) -> None:
        if self._file is not None:
            return
        self._file = open(self._path, "rb")
        self._reader = make_reader(self._file)
        self._summary = self._reader.get_summary()
        if self._summary is None:
            raise RuntimeError(f"MCAP 文件缺少 summary 索引，无法快速扫描：{self._path}")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
            self._reader = None

    # ------------------------------------------------------------------
    # get_topic_names
    # ------------------------------------------------------------------

    def get_topic_names(self) -> List[str]:
        """返回 6 路相机图像 topic 列表，按 _CAMERA_ORDER 排序。"""
        if self._topic_names is not None:
            return self._topic_names

        assert self._summary is not None, "请先调用 open()"

        # 从 channels 中找所有图像 topic
        image_topics: set[str] = set()
        for ch in self._summary.channels.values():
            if ch.topic.endswith(_IMAGE_SUFFIX):
                image_topics.add(ch.topic)

        # 按 _CAMERA_ORDER 排序；未知相机追加在末尾
        def sort_key(t: str) -> int:
            cam = t.split("/")[1] if "/" in t else t
            try:
                return _CAMERA_ORDER.index(cam)
            except ValueError:
                return len(_CAMERA_ORDER)

        self._topic_names = sorted(image_topics, key=sort_key)
        return self._topic_names

    # ------------------------------------------------------------------
    # get_camera_info
    # ------------------------------------------------------------------

    def get_camera_info(self, topic_id: str) -> CameraInfo:
        """解码 foxglove.CameraCalibration，返回 CameraInfo。

        Args:
            topic_id: 图像 topic，如 '/CAM_FRONT/image_rect_compressed'。
        """
        if topic_id in self._camera_infos:
            return self._camera_infos[topic_id]

        # 对应的 camera_info topic
        cal_topic = topic_id.replace(_IMAGE_SUFFIX, _CALIBRATION_SUFFIX)

        decoder = DecoderFactory()
        with open(self._path, "rb") as f:
            reader = make_reader(f, decoder_factories=[decoder])
            for _schema, channel, _message, proto in reader.iter_decoded_messages(
                topics=[cal_topic]
            ):
                camera_id = proto.frame_id or channel.topic.split("/")[1]
                info = CameraInfo(
                    camera_id=camera_id,
                    topic=topic_id,
                    width=proto.width,
                    height=proto.height,
                    K=list(proto.K),
                    D=list(proto.D),
                    distortion_model=proto.distortion_model or "",
                    P=list(proto.P),
                    R=list(proto.R),
                )
                self._camera_infos[topic_id] = info
                return info

        raise ValueError(f"MCAP 中找不到 calibration channel：{cal_topic}")

    # ------------------------------------------------------------------
    # get_timeline
    # ------------------------------------------------------------------

    def get_timeline(self) -> Timeline:
        """扫描全部图像消息，构建时间戳对齐的 Timeline。

        锚点：CAM_FRONT（或列表第一路）。
        同步窗口：self._sync_window_ns（默认 50 ms）。
        """
        if self._timeline is not None:
            return self._timeline

        topics = self.get_topic_names()
        if not topics:
            raise RuntimeError("MCAP 中未找到任何图像 topic")

        anchor_topic = f"/{_CAMERA_ORDER[0]}{_IMAGE_SUFFIX}"
        if anchor_topic not in topics:
            anchor_topic = topics[0]

        # 1. 扫描所有图像 channel，按 topic 收集 (log_time, data_len) 列表
        msgs_by_topic: dict[str, list[tuple[int, int]]] = {t: [] for t in topics}

        with open(self._path, "rb") as f:
            reader = make_reader(f)
            for _schema, channel, message in reader.iter_messages(topics=topics):
                t = channel.topic
                if t in msgs_by_topic:
                    msgs_by_topic[t].append((message.log_time, len(message.data)))

        # 确保各路按时间排序
        for t in topics:
            msgs_by_topic[t].sort(key=lambda x: x[0])

        anchor_msgs = msgs_by_topic[anchor_topic]
        if not anchor_msgs:
            raise RuntimeError(f"锚点 topic {anchor_topic} 中无消息")

        # 2. 对每个锚点时间戳，在其他路中找最近帧（在同步窗口内）
        # 使用指针法，O(N) 每路
        other_topics = [t for t in topics if t != anchor_topic]
        # 指针：指向各路下一个待检查的消息索引
        pointers: dict[str, int] = {t: 0 for t in other_topics}

        entries: list[TimelineEntry] = []

        for anchor_ts, anchor_len in anchor_msgs:
            entry = TimelineEntry(
                timestamp_ns=anchor_ts,
                frames={
                    anchor_topic: FrameRef(
                        topic=anchor_topic,
                        timestamp_ns=anchor_ts,
                        log_offset=0,
                        data_length=anchor_len,
                    )
                },
            )

            for t in other_topics:
                msgs = msgs_by_topic[t]
                ptr = pointers[t]

                # 推进指针：跳过所有时间戳比 anchor_ts - window 早的消息
                while ptr < len(msgs) and msgs[ptr][0] < anchor_ts - self._sync_window_ns:
                    ptr += 1
                pointers[t] = ptr

                # 在窗口范围内找时间差最小的消息
                best_ts, best_len, best_diff = None, 0, self._sync_window_ns + 1
                scan = ptr
                while scan < len(msgs) and msgs[scan][0] <= anchor_ts + self._sync_window_ns:
                    diff = abs(msgs[scan][0] - anchor_ts)
                    if diff < best_diff:
                        best_diff = diff
                        best_ts, best_len = msgs[scan]
                    scan += 1

                if best_ts is not None:
                    entry.frames[t] = FrameRef(
                        topic=t,
                        timestamp_ns=best_ts,
                        log_offset=0,
                        data_length=best_len,
                    )

            entries.append(entry)

        self._timeline = Timeline(
            source_path=str(self._path.resolve()),
            camera_topics=topics,
            entries=entries,
        )
        return self._timeline

    # ------------------------------------------------------------------
    # iter_frames
    # ------------------------------------------------------------------

    def iter_frames(
        self,
        t_start: int,
        t_end: int,
        camera_topic_ids: List[str],
    ) -> Iterator[MultiCameraFrame]:
        """按 Timeline entries 流式 yield MultiCameraFrame。

        使用 log_time 范围过滤（mcap 内建索引），不整包加载。
        每个 entry 聚合 6 路帧，JPEG bytes 直接透传（不解压）。
        """
        # 先确保 timeline 已构建，用于 entry 聚合边界
        timeline = self.get_timeline()
        entries_in_range = timeline.slice(t_start, t_end)
        if not entries_in_range:
            return

        topics_set = set(camera_topic_ids)
        # 仅迭代所需 topic
        topics_to_read = [t for t in camera_topic_ids if t in topics_set]

        # 按 entry 的 timestamp_ns 建立快速查找表：
        # entry_map[anchor_ts][topic] = expected_ts（FrameRef.timestamp_ns）
        entry_map: dict[int, TimelineEntry] = {e.timestamp_ns: e for e in entries_in_range}
        t_start_query = entries_in_range[0].timestamp_ns - self._sync_window_ns
        t_end_query = entries_in_range[-1].timestamp_ns + self._sync_window_ns

        # 按 topic 收集消息：{topic: {log_time: image_bytes}}
        # 只扫描所需时间范围，利用 MCAP 内建时间索引
        buffers: dict[str, dict[int, bytes]] = {t: {} for t in topics_to_read}

        decoder = DecoderFactory()
        with open(self._path, "rb") as f:
            reader = make_reader(f, decoder_factories=[decoder])
            for _schema, channel, message, proto in reader.iter_decoded_messages(
                topics=topics_to_read,
                start_time=t_start_query,
                end_time=t_end_query,
            ):
                buffers[channel.topic][message.log_time] = bytes(proto.data)

        # 按 entry 顺序聚合并 yield
        for entry in entries_in_range:
            frames: dict[str, Frame] = {}

            for t, ref in entry.frames.items():
                if t not in topics_set:
                    continue
                img = buffers.get(t, {}).get(ref.timestamp_ns)
                if img is None:
                    continue

                cam_id = t.split("/")[1] if "/" in t else t
                frames[cam_id] = Frame(
                    camera_id=cam_id,
                    topic=t,
                    timestamp_ns=ref.timestamp_ns,
                    image_data=img,
                    image_format="jpeg",
                )

            if frames:
                yield MultiCameraFrame(
                    timestamp_ns=entry.timestamp_ns,
                    frames=frames,
                )
