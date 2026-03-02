"""SceneSplitter — 将整段 Timeline 按时间或距离切分为多个 sub-scene。

配置来自 config/scene_split.yaml：
    mode: time         # time | distance
    interval_sec: 20   # time 模式：每 N 秒一个 scene
    min_frames: 50     # 不足此帧数的 sub-scene 合并到上一 scene

每个 sub-scene 生成唯一 scene_id，如 "scene-0061_s0"、"scene-0061_s1"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ad_3dgs.types import SceneData, Timeline


class SceneSplitter:
    """将 Timeline 切分为多个 SceneData 的工厂类。

    Args:
        mode:         划分模式，'time' 或 'distance'（distance 模式为预留，当前按 time）。
        interval_sec: time 模式下每个 scene 的最大时长（秒）。
        min_frames:   sub-scene 最少帧数；不足时合并到上一 scene（避免产生太短 scene）。
    """

    def __init__(
        self,
        mode: str = "time",
        interval_sec: float = 20.0,
        min_frames: int = 50,
    ) -> None:
        if mode not in ("time", "distance"):
            raise ValueError(f"不支持的划分模式：{mode}，应为 'time' 或 'distance'")
        self.mode = mode
        self.interval_ns = int(interval_sec * 1_000_000_000)
        self.min_frames = min_frames

    # ------------------------------------------------------------------
    # 主接口
    # ------------------------------------------------------------------

    def split(
        self,
        timeline: Timeline,
        mcap_path: str,
        base_output_dir: str,
        scene_name: Optional[str] = None,
    ) -> list[SceneData]:
        """将 timeline 切分为多个 SceneData。

        Args:
            timeline:        完整 Timeline（ILogReader.get_timeline() 的返回值）。
            mcap_path:       原始 MCAP 文件路径（写入 SceneData.source_mcap）。
            base_output_dir: 各 sub-scene 训练数据的父目录，
                             每个 sub-scene 写入 <base_output_dir>/<scene_id>/。
            scene_name:      scene 基础名称（默认取 mcap 文件 stem，去掉版本前缀）。
                             如 "NuScenes-v1.0-mini-scene-0061" → "scene-0061"。

        Returns:
            list[SceneData]，按时间顺序排列。若 Timeline 时长 <= interval_sec，
            返回单个 SceneData（不切分）。
        """
        if not timeline.entries:
            return []

        if scene_name is None:
            stem = Path(mcap_path).stem
            # "NuScenes-v1.0-mini-scene-0061" → "scene-0061"
            parts = stem.split("-")
            idx = next((i for i, p in enumerate(parts) if p == "scene"), -1)
            scene_name = "-".join(parts[idx:]) if idx >= 0 else stem

        if self.mode == "time":
            sub_timelines = self._split_by_time(timeline)
        else:
            # distance 模式预留：暂退化为 time 模式
            sub_timelines = self._split_by_time(timeline)

        # 合并过短的 sub-scene 到上一个
        sub_timelines = self._merge_short(sub_timelines)

        base = Path(base_output_dir)
        scenes = []
        for i, sub_tl in enumerate(sub_timelines):
            sid = f"{scene_name}_s{i}"
            scenes.append(
                SceneData(
                    scene_id=sid,
                    source_mcap=str(Path(mcap_path).resolve()),
                    timeline=sub_tl,
                    output_dir=str(base / sid),
                )
            )
        return scenes

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _split_by_time(self, timeline: Timeline) -> list[Timeline]:
        """按 interval_ns 切分 Timeline。"""
        if not timeline.entries:
            return []

        t0 = timeline.entries[0].timestamp_ns
        buckets: list[list] = [[]]

        for entry in timeline.entries:
            elapsed = entry.timestamp_ns - t0
            bucket_idx = int(elapsed // self.interval_ns)
            # 确保 buckets 足够长
            while len(buckets) <= bucket_idx:
                buckets.append([])
            buckets[bucket_idx].append(entry)

        result = []
        for bucket in buckets:
            if not bucket:
                continue
            sub_tl = Timeline(
                source_path=timeline.source_path,
                camera_topics=list(timeline.camera_topics),
                entries=bucket,
                start_ns=bucket[0].timestamp_ns,
                end_ns=bucket[-1].timestamp_ns,
            )
            result.append(sub_tl)
        return result

    def _merge_short(self, sub_timelines: list[Timeline]) -> list[Timeline]:
        """将帧数 < min_frames 的 sub-scene 合并到前一个 scene（或后一个）。"""
        if not sub_timelines:
            return []

        merged: list[Timeline] = []
        for sub_tl in sub_timelines:
            if merged and len(sub_tl.entries) < self.min_frames:
                # 合并到上一个
                prev = merged[-1]
                new_entries = prev.entries + sub_tl.entries
                merged[-1] = Timeline(
                    source_path=prev.source_path,
                    camera_topics=prev.camera_topics,
                    entries=new_entries,
                    start_ns=new_entries[0].timestamp_ns,
                    end_ns=new_entries[-1].timestamp_ns,
                )
            else:
                merged.append(sub_tl)

        return merged
