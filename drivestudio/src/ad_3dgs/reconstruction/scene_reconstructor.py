"""ISceneReconstructor — 3D 重建层抽象接口。

职责：以多视角图像 + 相机内外参为输入，训练 3DGS（或等价神经辐射场），
      并支持从 checkpoint 恢复。具体实现对上层屏蔽重建框架细节。

主实现：SceneReconstructorNerfstudio（见 nerfstudio_reconstructor.py）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ad_3dgs.types import SceneData, SceneHandle


class ISceneReconstructor(ABC):
    """3D 场景重建器抽象基类。

    典型使用流程：
        reconstructor = SceneReconstructorNerfstudio(config)
        scene_data = reconstructor.prepare_scene(raw_scene_data)
        handle = reconstructor.train(scene_data, config, checkpoint_dir)
        # 中断后恢复：
        handle = reconstructor.load_checkpoint(checkpoint_dir)
        handle = reconstructor.train(scene_data, config, checkpoint_dir)  # 自动 resume
    """

    # ------------------------------------------------------------------
    # 数据准备
    # ------------------------------------------------------------------

    @abstractmethod
    def prepare_scene(self, scene_data: SceneData) -> SceneData:
        """从 SceneData.timeline 提取图像和相机位姿，写入 scene_data.output_dir。

        具体产出（nerfstudio 实现）：
            <output_dir>/images/CAM_FRONT_frame_0000.jpg  ...
            <output_dir>/transforms.json

        Args:
            scene_data: 包含 timeline / camera_infos / output_dir 的 scene 描述。

        Returns:
            更新了 output_dir 内容后的 SceneData（原地修改，同时返回自身）。
        """

    # ------------------------------------------------------------------
    # 训练
    # ------------------------------------------------------------------

    @abstractmethod
    def train(
        self,
        scene_data: SceneData,
        config: dict,
        checkpoint_dir: str,
    ) -> SceneHandle:
        """启动或恢复 3DGS 训练。

        若 checkpoint_dir 中已存在 nerfstudio checkpoint，则自动 resume（
        通过 --load-dir 参数），不从头重跑。

        Args:
            scene_data:      经 prepare_scene() 处理后的 SceneData。
            config:          训练超参，键名与 reconstruction.yaml 一致
                             （max_num_iterations, max_gpu_memory_gb 等）。
            checkpoint_dir:  训练 checkpoint 的落盘目录。

        Returns:
            SceneHandle：is_complete=True 表示训练完成，False 表示中断。
        """

    # ------------------------------------------------------------------
    # Checkpoint 管理
    # ------------------------------------------------------------------

    @abstractmethod
    def save_checkpoint(self, scene_handle: SceneHandle, path: str | Path) -> Path:
        """将当前训练状态（nerfstudio ckpt 目录）软链接或复制到指定路径。

        用于 ICheckpointManager 统一管理多 scene 的 checkpoint。
        """

    @abstractmethod
    def load_checkpoint(self, path: str | Path) -> SceneHandle:
        """从 checkpoint 目录恢复 SceneHandle（不启动训练）。

        用于查询训练进度或准备 resume。
        """

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @abstractmethod
    def is_trained(self, scene_data: SceneData) -> bool:
        """判断该 scene 是否已训练完成（checkpoint 存在且标记为 complete）。"""

    def get_latest_checkpoint_step(self, checkpoint_dir: str | Path) -> int:
        """返回 checkpoint 目录中最新的训练步数（无 checkpoint 返回 0）。

        默认实现：扫描 nerfstudio 的 step-<N>.ckpt 文件名提取步数。
        子类可覆盖以适配不同框架的 checkpoint 命名规则。
        """
        ckpt_dir = Path(checkpoint_dir)
        if not ckpt_dir.exists():
            return 0
        steps = []
        for p in ckpt_dir.glob("step-*.ckpt"):
            try:
                steps.append(int(p.stem.split("-")[1]))
            except (IndexError, ValueError):
                pass
        return max(steps, default=0)
