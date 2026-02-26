"""NerfstudioDataExporter — 从 MCAP Timeline 导出 nerfstudio 训练数据。

输出目录结构（nerfstudio transforms.json 格式）：
    <output_dir>/
        images/
            CAM_FRONT_frame_0000.jpg
            CAM_FRONT_LEFT_frame_0000.jpg
            ...（6路 × N帧）
        transforms.json

transforms.json 遵循 nerfstudio instant-ngp/splatfacto 约定：
    - 每个 frame 包含 file_path（相对路径）+ transform_matrix（4×4 world_T_cam）
    - 相机内参写在顶层（fl_x/fl_y/cx/cy/w/h）
    - 若有多个相机，每帧写入所有相机（路数×帧数条目）
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from ad_3dgs.io.pose_extractor import PoseExtractor
from ad_3dgs.io.reader_mcap import LogReaderMcap
from ad_3dgs.types import CameraInfo, CameraPose, SceneData


class NerfstudioDataExporter:
    """从 SceneData 中提取图像和相机位姿，写出 nerfstudio 训练数据目录。

    Args:
        image_scale: 图像下采样比例（0.5 → 800×450，默认 0.5）。
        verbose:     是否打印进度。
    """

    def __init__(self, image_scale: float = 0.5, verbose: bool = True) -> None:
        self.image_scale = image_scale
        self.verbose = verbose

    # ------------------------------------------------------------------
    # 主接口
    # ------------------------------------------------------------------

    def export(self, scene_data: SceneData) -> SceneData:
        """导出图像和 transforms.json 到 scene_data.output_dir。

        Args:
            scene_data: 需要 scene_data.source_mcap / timeline / output_dir。
                        camera_infos 若为空则从 MCAP 自动加载。

        Returns:
            更新了 camera_infos（若原为空）的 scene_data（原地修改）。
        """
        out_dir = Path(scene_data.output_dir)
        img_dir = out_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)

        mcap_path = scene_data.source_mcap
        timeline = scene_data.timeline

        # 1. 加载相机内参（如果 scene_data 未提供）
        if not scene_data.camera_infos:
            with LogReaderMcap(mcap_path) as r:
                topics = r.get_topic_names()
                scene_data.camera_infos = {
                    t.split("/")[1]: r.get_camera_info(t) for t in topics
                }

        camera_infos = scene_data.camera_infos

        # 2. 提取相机位姿
        if self.verbose:
            print(f"[DataExporter] {scene_data.scene_id}: 提取相机位姿 ...")
        extractor = PoseExtractor(mcap_path)
        poses_by_cam = extractor.extract(timeline)

        # 3. 导出图像帧
        if self.verbose:
            print(f"[DataExporter] {scene_data.scene_id}: 导出图像到 {img_dir} ...")
        frames_json: list[dict] = []
        frame_idx = 0

        with LogReaderMcap(mcap_path) as r:
            topics = r.get_topic_names()
            for multi_frame in r.iter_frames(
                timeline.start_ns, timeline.end_ns, topics
            ):
                for cam_id, frame in multi_frame.frames.items():
                    img_filename = f"{cam_id}_frame_{frame_idx:04d}.jpg"
                    img_path = img_dir / img_filename

                    # 图像下采样（若 image_scale != 1.0）
                    img_bytes = self._maybe_resize(frame.image_data, self.image_scale)
                    img_path.write_bytes(img_bytes)

                    # 找对应位姿（从 poses_by_cam 中按 frame_idx 取）
                    cam_poses = poses_by_cam.get(cam_id, [])
                    if frame_idx < len(cam_poses):
                        transform = cam_poses[frame_idx].transform
                    else:
                        transform = [float(i == j) for i in range(4) for j in range(4)]

                    # 将 4×4 行优先 list 重排为 4×4 嵌套列表（nerfstudio 格式）
                    mat4 = [[transform[r*4+c] for c in range(4)] for r in range(4)]

                    ci = camera_infos.get(cam_id)
                    frame_entry = {
                        "file_path": f"images/{img_filename}",
                        "transform_matrix": mat4,
                        "camera_id": cam_id,
                    }
                    if ci is not None:
                        frame_entry["fl_x"] = ci.fx * self.image_scale
                        frame_entry["fl_y"] = ci.fy * self.image_scale
                        frame_entry["cx"] = ci.cx * self.image_scale
                        frame_entry["cy"] = ci.cy * self.image_scale
                        frame_entry["w"] = int(ci.width * self.image_scale)
                        frame_entry["h"] = int(ci.height * self.image_scale)
                    frames_json.append(frame_entry)

                frame_idx += 1

        # 4. 写 transforms.json
        # 取第一个相机的内参作为顶层默认值（nerfstudio 兼容性）
        first_ci: Optional[CameraInfo] = next(iter(camera_infos.values()), None)
        transforms = {
            "camera_model": "OPENCV",
            "fl_x": (first_ci.fx * self.image_scale) if first_ci else 1.0,
            "fl_y": (first_ci.fy * self.image_scale) if first_ci else 1.0,
            "cx": (first_ci.cx * self.image_scale) if first_ci else 0.0,
            "cy": (first_ci.cy * self.image_scale) if first_ci else 0.0,
            "w": int(first_ci.width * self.image_scale) if first_ci else 1,
            "h": int(first_ci.height * self.image_scale) if first_ci else 1,
            "k1": 0.0, "k2": 0.0, "p1": 0.0, "p2": 0.0,
            "frames": frames_json,
        }

        transforms_path = out_dir / "transforms.json"
        with open(transforms_path, "w", encoding="utf-8") as f:
            json.dump(transforms, f, indent=2)

        if self.verbose:
            n_imgs = len(frames_json)
            print(
                f"[DataExporter] {scene_data.scene_id}: 完成 "
                f"({n_imgs} 图像, transforms.json 写入 {transforms_path})"
            )

        return scene_data

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _maybe_resize(jpeg_bytes: bytes, scale: float) -> bytes:
        """若 scale != 1.0，使用 PIL 下采样图像；否则直接返回原始字节。"""
        if abs(scale - 1.0) < 1e-6:
            return jpeg_bytes

        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(jpeg_bytes))
            new_w = int(img.width * scale)
            new_h = int(img.height * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            return buf.getvalue()
        except ImportError:
            # PIL 未安装时直接返回原始字节
            return jpeg_bytes
