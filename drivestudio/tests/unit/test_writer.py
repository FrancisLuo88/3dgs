"""单元测试：LogWriterMcap（Phase 1.2）含 roundtrip 验证。

使用真实 MCAP 文件读取原始帧，写入临时 MCAP，再读回验证。
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_MCAP_PATH = _REPO_ROOT / "data" / "input" / "NuScenes-v1.0-mini-scene-0061.mcap"

pytestmark = pytest.mark.skipif(
    not _MCAP_PATH.exists(),
    reason=f"测试 MCAP 文件不存在：{_MCAP_PATH}",
)

from ad_3dgs.io.reader_mcap import LogReaderMcap
from ad_3dgs.io.writer_mcap import LogWriterMcap
from ad_3dgs.types import CompositeFrame, MultiCameraFrame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_composite(mf: MultiCameraFrame) -> dict[str, CompositeFrame]:
    """把 MultiCameraFrame 中的 Frame 转为 CompositeFrame（直接透传 image_data）。"""
    return {
        cam_id: CompositeFrame(
            camera_id=cam_id,
            timestamp_ns=frame.timestamp_ns,
            image_data=frame.image_data,
            image_format=frame.image_format,
        )
        for cam_id, frame in mf.frames.items()
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def source_data():
    """读取原始 MCAP 的前 5 帧及 camera_infos，供各测试共用。"""
    with LogReaderMcap(_MCAP_PATH) as r:
        topics = r.get_topic_names()
        tl = r.get_timeline()
        camera_infos = {t.split("/")[1]: r.get_camera_info(t) for t in topics}
        frames = list(r.iter_frames(tl.start_ns, tl.entries[4].timestamp_ns, topics))
    return {"frames": frames, "camera_infos": camera_infos, "timeline": tl}


@pytest.fixture()
def tmp_mcap(tmp_path):
    """每个测试用独立临时 MCAP 路径。"""
    return tmp_path / "output.mcap"


# ---------------------------------------------------------------------------
# 测试 open / close
# ---------------------------------------------------------------------------


def test_write_open_close(source_data, tmp_mcap):
    """写入后文件应存在且 size > 0。"""
    ci = source_data["camera_infos"]
    with LogWriterMcap(tmp_mcap, ci, ref_mcap_path=_MCAP_PATH) as w:
        mf = source_data["frames"][0]
        w.write_sync_point(mf.timestamp_ns, _make_composite(mf))

    assert tmp_mcap.exists()
    assert tmp_mcap.stat().st_size > 0


# ---------------------------------------------------------------------------
# Roundtrip 测试
# ---------------------------------------------------------------------------


def test_roundtrip_timestamp(source_data, tmp_mcap):
    """读→写→再读，re-read 的 timestamp_ns 应与原始逐一相等。"""
    ci = source_data["camera_infos"]
    orig_frames = source_data["frames"]

    with LogWriterMcap(tmp_mcap, ci, ref_mcap_path=_MCAP_PATH) as w:
        for mf in orig_frames:
            w.write_sync_point(mf.timestamp_ns, _make_composite(mf))

    with LogReaderMcap(tmp_mcap) as r:
        tl = r.get_timeline()

    assert len(tl) == len(orig_frames), f"帧数不匹配：{len(tl)} != {len(orig_frames)}"
    for i, (entry, orig) in enumerate(zip(tl.entries, orig_frames)):
        assert entry.timestamp_ns == orig.timestamp_ns, (
            f"第 {i} 帧时间戳不匹配：{entry.timestamp_ns} != {orig.timestamp_ns}"
        )


def test_roundtrip_image_bytes(source_data, tmp_mcap):
    """re-read 图像字节应与原始完全一致（无损传输）。"""
    ci = source_data["camera_infos"]
    orig_frames = source_data["frames"]

    with LogWriterMcap(tmp_mcap, ci, ref_mcap_path=_MCAP_PATH) as w:
        for mf in orig_frames:
            w.write_sync_point(mf.timestamp_ns, _make_composite(mf))

    topics = list(f"/{cam_id}/image_rect_compressed" for cam_id in ci)
    with LogReaderMcap(tmp_mcap) as r:
        tl = r.get_timeline()
        reread = list(r.iter_frames(tl.start_ns, tl.end_ns, topics))

    assert len(reread) == len(orig_frames)
    for mf_orig, mf_rr in zip(orig_frames, reread):
        for cam_id in mf_orig.frames:
            if cam_id not in mf_rr.frames:
                continue
            orig_img = mf_orig.frames[cam_id].image_data
            rr_img = mf_rr.frames[cam_id].image_data
            assert orig_img == rr_img, (
                f"cam={cam_id} ts={mf_orig.timestamp_ns} 图像字节不一致"
            )


def test_roundtrip_six_topics(source_data, tmp_mcap):
    """输出 MCAP 中应存在 6 路图像 topic（+ 6 路 camera_info topic）。"""
    ci = source_data["camera_infos"]
    orig_frames = source_data["frames"]

    with LogWriterMcap(tmp_mcap, ci, ref_mcap_path=_MCAP_PATH) as w:
        for mf in orig_frames:
            w.write_sync_point(mf.timestamp_ns, _make_composite(mf))

    with LogReaderMcap(tmp_mcap) as r:
        topics = r.get_topic_names()

    assert len(topics) == 6, f"期望 6 路 image topic，实际 {len(topics)}: {topics}"


def test_write_sync_point_same_timestamp(source_data, tmp_mcap):
    """write_sync_point 写入的 6 路帧，在输出 MCAP 中 log_time 应相同。"""
    ci = source_data["camera_infos"]
    mf = source_data["frames"][0]
    sync_ts = mf.timestamp_ns

    with LogWriterMcap(tmp_mcap, ci, ref_mcap_path=_MCAP_PATH) as w:
        w.write_sync_point(sync_ts, _make_composite(mf))

    # 直接用 mcap raw reader 检查每条消息的 log_time
    from mcap.reader import make_reader as _make_reader
    img_topics = [f"/{cam_id}/image_rect_compressed" for cam_id in ci]
    log_times = []
    with open(tmp_mcap, "rb") as f:
        raw = _make_reader(f)
        for _, channel, message in raw.iter_messages(topics=img_topics):
            log_times.append(message.log_time)

    assert len(log_times) == len(mf.frames), f"图像消息数 {len(log_times)} != {len(mf.frames)}"
    assert all(t == sync_ts for t in log_times), (
        f"log_time 不全等于 {sync_ts}：{log_times}"
    )
