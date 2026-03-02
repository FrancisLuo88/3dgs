"""单元测试：LogReaderMcap（Phase 1.1 / 1.3）

使用真实 MCAP 文件：data/input/NuScenes-v1.0-mini-scene-0061.mcap
若文件不存在则整套测试跳过（CI 环境中可选跳过大文件测试）。
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

# 测试用 MCAP 路径（相对于仓库根）
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_MCAP_PATH = _REPO_ROOT / "data" / "input" / "NuScenes-v1.0-mini-scene-0061.mcap"

pytestmark = pytest.mark.skipif(
    not _MCAP_PATH.exists(),
    reason=f"测试 MCAP 文件不存在：{_MCAP_PATH}",
)

from ad_3dgs.io.reader_mcap import LogReaderMcap
from ad_3dgs.types import CameraInfo, MultiCameraFrame, Timeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reader():
    """模块级 reader，避免每个测试重复打开大文件。"""
    r = LogReaderMcap(_MCAP_PATH, sync_window_ms=50)
    r.open()
    yield r
    r.close()


@pytest.fixture(scope="module")
def timeline(reader):
    return reader.get_timeline()


# ---------------------------------------------------------------------------
# 测试 get_topic_names
# ---------------------------------------------------------------------------


def test_get_topic_names_count(reader):
    """应返回恰好 6 个图像 topic。"""
    topics = reader.get_topic_names()
    assert len(topics) == 6, f"期望 6 个 topic，实际 {len(topics)}: {topics}"


def test_get_topic_names_suffix(reader):
    """所有 topic 应以 image_rect_compressed 结尾。"""
    for t in reader.get_topic_names():
        assert t.endswith("/image_rect_compressed"), f"意外 topic：{t}"


def test_get_topic_names_cam_front_first(reader):
    """CAM_FRONT 应排在第一位。"""
    topics = reader.get_topic_names()
    assert topics[0] == "/CAM_FRONT/image_rect_compressed"


# ---------------------------------------------------------------------------
# 测试 get_camera_info
# ---------------------------------------------------------------------------


def test_get_camera_info_cam_front(reader):
    """CAM_FRONT 内参应与 nuScenes 标定数据一致。"""
    ci = reader.get_camera_info("/CAM_FRONT/image_rect_compressed")
    assert isinstance(ci, CameraInfo)
    assert ci.width == 1600
    assert ci.height == 900
    assert abs(ci.fx - 1266.4) < 1.0, f"fx 偏差过大：{ci.fx}"
    assert abs(ci.fy - 1266.4) < 1.0, f"fy 偏差过大：{ci.fy}"
    assert abs(ci.cx - 816.3) < 1.0, f"cx 偏差过大：{ci.cx}"
    assert len(ci.K) == 9


def test_get_camera_info_all_cameras(reader):
    """6 路相机均应可以读取到有效 CameraInfo。"""
    for topic in reader.get_topic_names():
        ci = reader.get_camera_info(topic)
        assert ci.width > 0 and ci.height > 0, f"{topic} 分辨率为 0"
        assert len(ci.K) == 9, f"{topic} K 矩阵长度不为 9"


# ---------------------------------------------------------------------------
# 测试 get_timeline
# ---------------------------------------------------------------------------


def test_timeline_entry_count(timeline):
    """Timeline entry 数量应与 CAM_FRONT 消息数一致（scene-0061: 224 帧）。"""
    assert len(timeline) == 224, f"期望 224 entries，实际 {len(timeline)}"


def test_timeline_timestamp_monotonic(timeline):
    """所有 entry 的 timestamp_ns 应严格单调递增。"""
    ts = [e.timestamp_ns for e in timeline.entries]
    for i in range(1, len(ts)):
        assert ts[i] > ts[i - 1], f"第 {i} 个时间戳不递增：{ts[i-1]} >= {ts[i]}"


def test_timeline_six_topics_per_entry(timeline):
    """6 路齐全率应 >=80%；nuScenes 数据真实存在偶发缺帧（CAM_BACK 等），属正常。"""
    full_entries = sum(1 for e in timeline.entries if len(e.frames) == 6)
    ratio = full_entries / len(timeline)
    assert ratio >= 0.80, f"6 路齐全率 {ratio:.1%} 低于 80%（可能同步窗口过小）"

    # 最少也应有 1 路（确认 entry 本身有效）
    min_topics = min(len(e.frames) for e in timeline.entries)
    assert min_topics >= 1, "存在空 entry"


def test_timeline_start_end(timeline):
    """start_ns / end_ns 应与 entries 一致。"""
    assert timeline.start_ns == timeline.entries[0].timestamp_ns
    assert timeline.end_ns == timeline.entries[-1].timestamp_ns


# ---------------------------------------------------------------------------
# 测试 Timeline 序列化
# ---------------------------------------------------------------------------


def test_timeline_serialization_roundtrip(timeline):
    """save → load 后 entries 数量、首末时间戳、topics 完全一致。"""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = pathlib.Path(f.name)

    try:
        timeline.save(tmp)
        assert tmp.exists() and tmp.stat().st_size > 0

        tl2 = Timeline.load(tmp)
        assert len(tl2) == len(timeline)
        assert tl2.start_ns == timeline.start_ns
        assert tl2.end_ns == timeline.end_ns
        assert tl2.camera_topics == timeline.camera_topics

        # 首帧每路 FrameRef 的 timestamp_ns 一致
        for topic, ref in timeline.entries[0].frames.items():
            assert topic in tl2.entries[0].frames
            assert tl2.entries[0].frames[topic].timestamp_ns == ref.timestamp_ns
    finally:
        tmp.unlink(missing_ok=True)


def test_timeline_json_version(timeline):
    """JSON 文件应包含 version=1 字段。"""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = pathlib.Path(f.name)
    try:
        timeline.save(tmp)
        data = json.loads(tmp.read_text())
        assert data["version"] == 1
        assert "entries" in data
        assert "source_path" in data
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 测试 iter_frames
# ---------------------------------------------------------------------------


def test_iter_frames_total_count(reader, timeline):
    """全范围迭代应与 Timeline entry 数一致。"""
    frames = list(reader.iter_frames(timeline.start_ns, timeline.end_ns, reader.get_topic_names()))
    assert len(frames) == len(timeline)


def test_iter_frames_image_is_jpeg(reader, timeline):
    """每帧图像应是合法 JPEG（魔数 FF D8）。"""
    topics = reader.get_topic_names()
    # 只取前 5 帧验证，节省时间
    first_five = list(reader.iter_frames(
        timeline.start_ns,
        timeline.entries[4].timestamp_ns,
        topics,
    ))
    assert len(first_five) == 5
    for mf in first_five:
        assert isinstance(mf, MultiCameraFrame)
        for cam_id, frame in mf.frames.items():
            assert frame.image_data[:2] == b"\xff\xd8", (
                f"{cam_id} 图像不是 JPEG，magic={frame.image_data[:2].hex()}"
            )


def test_iter_frames_time_range(reader, timeline):
    """time range 过滤：只返回指定范围内的 entries。"""
    first_10_end = timeline.entries[9].timestamp_ns
    frames = list(reader.iter_frames(timeline.start_ns, first_10_end, reader.get_topic_names()))
    assert len(frames) == 10


def test_iter_frames_timestamp_matches_timeline(reader, timeline):
    """iter_frames 返回的 MultiCameraFrame.timestamp_ns 应与对应 TimelineEntry 一致。"""
    topics = reader.get_topic_names()
    for mf, entry in zip(
        reader.iter_frames(timeline.start_ns, timeline.entries[4].timestamp_ns, topics),
        timeline.entries[:5],
    ):
        assert mf.timestamp_ns == entry.timestamp_ns
