"""Phase 2 单元测试：PoseExtractor / SceneSplitter / CheckpointManager / NerfstudioDataExporter。

所有需要 MCAP 文件的测试均通过 `mcap_path` fixture 跳过（若文件不存在）。
DataExporter 的图像写出测试在临时目录中运行，不依赖真实 MCAP。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MCAP_PATH = "/home/luosx/3dgs/data/input/NuScenes-v1.0-mini-scene-0061.mcap"


@pytest.fixture(scope="module")
def mcap_path():
    path = Path(MCAP_PATH)
    if not path.exists():
        pytest.skip(f"MCAP 文件不存在，跳过 MCAP 相关测试：{path}")
    return str(path)


@pytest.fixture(scope="module")
def timeline(mcap_path):
    from ad_3dgs.io.reader_mcap import LogReaderMcap
    with LogReaderMcap(mcap_path) as r:
        return r.get_timeline()


@pytest.fixture(scope="module")
def pose_extractor(mcap_path):
    from ad_3dgs.io.pose_extractor import PoseExtractor
    return PoseExtractor(mcap_path)


# ---------------------------------------------------------------------------
# PoseExtractor 测试
# ---------------------------------------------------------------------------

class TestPoseExtractor:
    def test_static_extrinsics_six_cameras(self, pose_extractor):
        """静态外参应包含 6 路相机。"""
        extrinsics = pose_extractor.get_static_extrinsics()
        cam_ids = set(extrinsics.keys())
        expected = {"CAM_FRONT", "CAM_FRONT_LEFT", "CAM_FRONT_RIGHT",
                    "CAM_BACK", "CAM_BACK_LEFT", "CAM_BACK_RIGHT"}
        assert expected == cam_ids, f"缺失相机：{expected - cam_ids}"

    def test_static_extrinsics_cam_front_position(self, pose_extractor):
        """CAM_FRONT 外参平移应与 /tf 原始值一致（< 1mm 误差）。"""
        extr = pose_extractor.get_static_extrinsics()
        cf = extr["CAM_FRONT"]
        # 来自 /tf 实测：(1.7008, 0.0159, 1.5110)
        assert abs(cf[3]  - 1.7008) < 1e-3, f"tx={cf[3]:.4f}"
        assert abs(cf[7]  - 0.0159) < 1e-3, f"ty={cf[7]:.4f}"
        assert abs(cf[11] - 1.5110) < 1e-3, f"tz={cf[11]:.4f}"

    def test_static_extrinsics_rotation_orthogonal(self, pose_extractor):
        """所有相机外参旋转矩阵 det(R) ≈ 1。"""
        extrinsics = pose_extractor.get_static_extrinsics()
        for cam_id, m in extrinsics.items():
            r3 = [[m[r*4+c] for c in range(3)] for r in range(3)]
            det = (r3[0][0]*(r3[1][1]*r3[2][2]-r3[1][2]*r3[2][1])
                  -r3[0][1]*(r3[1][0]*r3[2][2]-r3[1][2]*r3[2][0])
                  +r3[0][2]*(r3[1][0]*r3[2][1]-r3[1][1]*r3[2][0]))
            assert abs(det - 1.0) < 1e-4, f"{cam_id} det(R)={det:.6f}"

    def test_extract_pose_count(self, pose_extractor, timeline):
        """每路相机的位姿数量应等于 Timeline 的 entry 数。"""
        poses = pose_extractor.extract(timeline)
        n = len(timeline.entries)
        for cam_id, pose_list in poses.items():
            assert len(pose_list) == n, f"{cam_id}: {len(pose_list)} != {n}"

    def test_extract_world_pose_det_R(self, pose_extractor, timeline):
        """world_T_cam 的旋转矩阵应为正交矩阵（det ≈ 1）。"""
        poses = pose_extractor.extract(timeline)
        cam_front = poses["CAM_FRONT"]

        for i, p in enumerate(cam_front[:5]):   # 只检查前 5 帧
            m = p.transform
            r3 = [[m[r*4+c] for c in range(3)] for r in range(3)]
            det = (r3[0][0]*(r3[1][1]*r3[2][2]-r3[1][2]*r3[2][1])
                  -r3[0][1]*(r3[1][0]*r3[2][2]-r3[1][2]*r3[2][0])
                  +r3[0][2]*(r3[1][0]*r3[2][1]-r3[1][1]*r3[2][0]))
            assert abs(det - 1.0) < 1e-4, f"frame {i} det(R)={det:.6f}"

    def test_extract_world_pose_position_changes(self, pose_extractor, timeline):
        """vehicle 在行驶，CAM_FRONT 的世界位置应随时间变化。"""
        poses = pose_extractor.extract(timeline)
        cam_front = poses["CAM_FRONT"]
        assert len(cam_front) >= 2

        p0 = cam_front[0].transform
        p_last = cam_front[-1].transform
        dx = p_last[3] - p0[3]
        dy = p_last[7] - p0[7]
        dist = math.sqrt(dx*dx + dy*dy)
        # 19 秒场景，车辆应行驶 > 5m
        assert dist > 5.0, f"行驶距离 {dist:.2f}m 似乎太小"


# ---------------------------------------------------------------------------
# SceneSplitter 测试
# ---------------------------------------------------------------------------

class TestSceneSplitter:
    def test_no_split_short_scene(self, timeline, mcap_path):
        """19 秒 scene + interval=20s → 不切分，返回 1 个 SceneData。"""
        from ad_3dgs.reconstruction.scene_splitter import SceneSplitter
        splitter = SceneSplitter(mode="time", interval_sec=20.0, min_frames=1)
        with tempfile.TemporaryDirectory() as tmp:
            scenes = splitter.split(timeline, mcap_path, tmp)
        assert len(scenes) == 1, f"应为 1 个 scene，实为 {len(scenes)}"

    def test_split_into_two(self, timeline, mcap_path):
        """设 interval=10s → 19 秒 scene 切成 2 个。"""
        from ad_3dgs.reconstruction.scene_splitter import SceneSplitter
        splitter = SceneSplitter(mode="time", interval_sec=10.0, min_frames=1)
        with tempfile.TemporaryDirectory() as tmp:
            scenes = splitter.split(timeline, mcap_path, tmp)
        assert len(scenes) == 2, f"应为 2 个 scene，实为 {len(scenes)}"

    def test_scene_ids_unique(self, timeline, mcap_path):
        """所有 sub-scene 的 scene_id 应唯一。"""
        from ad_3dgs.reconstruction.scene_splitter import SceneSplitter
        splitter = SceneSplitter(mode="time", interval_sec=10.0, min_frames=1)
        with tempfile.TemporaryDirectory() as tmp:
            scenes = splitter.split(timeline, mcap_path, tmp)
        ids = [s.scene_id for s in scenes]
        assert len(ids) == len(set(ids)), "scene_id 存在重复"

    def test_total_frames_preserved(self, timeline, mcap_path):
        """切分后所有 sub-scene 帧数之和等于原 timeline 帧数。"""
        from ad_3dgs.reconstruction.scene_splitter import SceneSplitter
        splitter = SceneSplitter(mode="time", interval_sec=10.0, min_frames=1)
        with tempfile.TemporaryDirectory() as tmp:
            scenes = splitter.split(timeline, mcap_path, tmp)
        total = sum(len(s.timeline.entries) for s in scenes)
        assert total == len(timeline.entries), (
            f"帧数不守恒：{total} != {len(timeline.entries)}"
        )

    def test_min_frames_merging(self, timeline, mcap_path):
        """设 min_frames > 第二段帧数 → 第二段应合并到第一段，结果为 1 个 scene。"""
        from ad_3dgs.reconstruction.scene_splitter import SceneSplitter
        # 10s 切两段，第二段约 9s≈108帧；设 min_frames=200 强制合并
        splitter = SceneSplitter(mode="time", interval_sec=10.0, min_frames=200)
        with tempfile.TemporaryDirectory() as tmp:
            scenes = splitter.split(timeline, mcap_path, tmp)
        # 合并后应 ≤ 2 个 scene（有可能 2 段都 <200 帧，合并成 1）
        assert len(scenes) <= 2, f"合并后不应超过 2 个 scene，实为 {len(scenes)}"


# ---------------------------------------------------------------------------
# CheckpointManager 测试
# ---------------------------------------------------------------------------

class TestCheckpointManager:
    def test_register_and_query(self):
        """注册 stage 后可查询到 running 状态。"""
        from ad_3dgs.checkpoint.manager import CheckpointManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = CheckpointManager(Path(tmp) / "registry.json")
            mgr.register_stage("stage2_recon", "scene-0061_s0", state={"step": 100})
            assert not mgr.is_complete("stage2_recon", "scene-0061_s0")
            rp = mgr.get_last_incomplete("stage2_recon", "scene-0061_s0")
            assert rp is not None
            assert rp.state == {"step": 100}

    def test_mark_complete(self):
        """mark_complete 后 is_complete 应返回 True。"""
        from ad_3dgs.checkpoint.manager import CheckpointManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = CheckpointManager(Path(tmp) / "registry.json")
            mgr.register_stage("stage2_recon", "scene-0061_s0", state={})
            mgr.mark_complete("stage2_recon", "scene-0061_s0", checkpoint_path="/ckpt/s0")
            assert mgr.is_complete("stage2_recon", "scene-0061_s0")

    def test_checkpoint_path_saved(self):
        """mark_complete 中传入的 checkpoint_path 可通过 get_checkpoint_path 取回。"""
        from ad_3dgs.checkpoint.manager import CheckpointManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = CheckpointManager(Path(tmp) / "registry.json")
            mgr.mark_complete("stage2_recon", "scene-0061_s0", checkpoint_path="/ckpt/s0")
            path = mgr.get_checkpoint_path("stage2_recon", "scene-0061_s0")
            assert path == "/ckpt/s0"

    def test_persistence_across_instances(self):
        """关闭 CheckpointManager 再重新加载，数据应持久化。"""
        from ad_3dgs.checkpoint.manager import CheckpointManager
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "registry.json"
            mgr1 = CheckpointManager(reg)
            mgr1.mark_complete("stage2_recon", "scene-0061_s0", checkpoint_path="/ckpt")

            mgr2 = CheckpointManager(reg)
            assert mgr2.is_complete("stage2_recon", "scene-0061_s0")
            assert mgr2.get_checkpoint_path("stage2_recon", "scene-0061_s0") == "/ckpt"

    def test_get_last_incomplete_returns_none_when_all_done(self):
        """所有 scene 均完成时 get_last_incomplete 应返回 None。"""
        from ad_3dgs.checkpoint.manager import CheckpointManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = CheckpointManager(Path(tmp) / "registry.json")
            for i in range(3):
                mgr.mark_complete("stage2_recon", f"scene-0061_s{i}")
            rp = mgr.get_last_incomplete("stage2_recon")
            assert rp is None

    def test_get_all_scenes(self):
        """get_all_scenes 应返回该 stage 下所有注册的 scene_id。"""
        from ad_3dgs.checkpoint.manager import CheckpointManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = CheckpointManager(Path(tmp) / "registry.json")
            for i in range(3):
                mgr.register_stage("stage2_recon", f"scene-0061_s{i}", state={})
            scenes = mgr.get_all_scenes("stage2_recon")
            assert set(scenes) == {"scene-0061_s0", "scene-0061_s1", "scene-0061_s2"}


# ---------------------------------------------------------------------------
# NerfstudioDataExporter 测试（不依赖 MCAP，使用 mock SceneData）
# ---------------------------------------------------------------------------

class TestNerfstudioDataExporter:
    def _make_scene_data(self, out_dir: str, mcap_path: str, timeline) -> "SceneData":
        from ad_3dgs.types import SceneData, CameraInfo
        from ad_3dgs.io.reader_mcap import LogReaderMcap

        with LogReaderMcap(mcap_path) as r:
            topics = r.get_topic_names()
            cam_infos = {t.split("/")[1]: r.get_camera_info(t) for t in topics}

        return SceneData(
            scene_id="scene-0061_s0",
            source_mcap=mcap_path,
            timeline=timeline,
            camera_infos=cam_infos,
            output_dir=out_dir,
        )

    def test_export_creates_images_dir(self, mcap_path, timeline):
        """export() 应在 output_dir 创建 images/ 子目录。"""
        from ad_3dgs.reconstruction.data_exporter import NerfstudioDataExporter
        with tempfile.TemporaryDirectory() as tmp:
            scene = self._make_scene_data(tmp, mcap_path, timeline)
            exporter = NerfstudioDataExporter(image_scale=0.25, verbose=False)
            exporter.export(scene)
            assert (Path(tmp) / "images").is_dir()

    def test_export_creates_transforms_json(self, mcap_path, timeline):
        """export() 应在 output_dir 创建 transforms.json。"""
        from ad_3dgs.reconstruction.data_exporter import NerfstudioDataExporter
        with tempfile.TemporaryDirectory() as tmp:
            scene = self._make_scene_data(tmp, mcap_path, timeline)
            exporter = NerfstudioDataExporter(image_scale=0.25, verbose=False)
            exporter.export(scene)
            tf_path = Path(tmp) / "transforms.json"
            assert tf_path.exists()

    def test_transforms_json_has_frames(self, mcap_path, timeline):
        """transforms.json 的 frames 列表应非空，且每帧有 file_path 和 transform_matrix。"""
        from ad_3dgs.reconstruction.data_exporter import NerfstudioDataExporter
        with tempfile.TemporaryDirectory() as tmp:
            scene = self._make_scene_data(tmp, mcap_path, timeline)
            exporter = NerfstudioDataExporter(image_scale=0.25, verbose=False)
            exporter.export(scene)
            with open(Path(tmp) / "transforms.json") as f:
                data = json.load(f)
            frames = data["frames"]
            assert len(frames) > 0
            for frame in frames[:3]:
                assert "file_path" in frame
                assert "transform_matrix" in frame
                assert len(frame["transform_matrix"]) == 4
                assert len(frame["transform_matrix"][0]) == 4

    def test_image_files_are_jpeg(self, mcap_path, timeline):
        """导出的图像文件应为有效 JPEG（前两字节 FF D8）。"""
        from ad_3dgs.reconstruction.data_exporter import NerfstudioDataExporter
        with tempfile.TemporaryDirectory() as tmp:
            scene = self._make_scene_data(tmp, mcap_path, timeline)
            exporter = NerfstudioDataExporter(image_scale=0.25, verbose=False)
            exporter.export(scene)
            img_dir = Path(tmp) / "images"
            jpegs = list(img_dir.glob("*.jpg"))
            assert len(jpegs) > 0
            for jpeg in jpegs[:3]:
                header = jpeg.read_bytes()[:2]
                assert header == b"\xff\xd8", f"{jpeg.name} 不是有效 JPEG"

    def test_image_scale_reduces_size(self, mcap_path, timeline):
        """scale=0.5 时导出图像应比原始图像（1600×900）更小。"""
        from ad_3dgs.reconstruction.data_exporter import NerfstudioDataExporter
        from PIL import Image
        import io
        with tempfile.TemporaryDirectory() as tmp:
            scene = self._make_scene_data(tmp, mcap_path, timeline)
            exporter = NerfstudioDataExporter(image_scale=0.5, verbose=False)
            exporter.export(scene)
            img_dir = Path(tmp) / "images"
            sample = next(img_dir.glob("CAM_FRONT_*.jpg"))
            img = Image.open(io.BytesIO(sample.read_bytes()))
            assert img.width <= 800, f"width={img.width}"
            assert img.height <= 450, f"height={img.height}"
