"""SceneReconstructorNerfstudio — ISceneReconstructor 的 nerfstudio splatfacto 实现。

封装 `ns-train splatfacto` CLI，支持：
  - 从 SceneData 导出训练数据（调用 NerfstudioDataExporter）
  - 启动训练（subprocess 调用 ns-train）
  - 从 last checkpoint 自动 resume（--load-dir）
  - 从 checkpoint 目录恢复 SceneHandle（无需重新训练）

配置来自 config/reconstruction.yaml（通过 config dict 传入）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ad_3dgs.reconstruction.data_exporter import NerfstudioDataExporter
from ad_3dgs.reconstruction.scene_reconstructor import ISceneReconstructor
from ad_3dgs.types import SceneData, SceneHandle

# 默认训练配置（可被 train() 的 config 参数覆盖）
_DEFAULT_CONFIG = {
    "method": "splatfacto",
    "max_num_iterations": 30000,
    "image_scale": 0.5,
    "batch_size": 1,
    "save_checkpoint_every": 2000,
    "max_gpu_memory_gb": 6.0,
}


class SceneReconstructorNerfstudio(ISceneReconstructor):
    """nerfstudio splatfacto 训练器。

    Args:
        image_scale:  图像下采样比例，默认 0.5（覆盖 config 中的值）。
        verbose:      是否打印训练进度。
    """

    def __init__(self, image_scale: float = 0.5, verbose: bool = True) -> None:
        self.image_scale = image_scale
        self.verbose = verbose
        self._exporter = NerfstudioDataExporter(image_scale=image_scale, verbose=verbose)

    # ------------------------------------------------------------------
    # ISceneReconstructor 接口实现
    # ------------------------------------------------------------------

    def prepare_scene(self, scene_data: SceneData) -> SceneData:
        """导出图像和 transforms.json 到 scene_data.output_dir。"""
        return self._exporter.export(scene_data)

    def train(
        self,
        scene_data: SceneData,
        config: dict,
        checkpoint_dir: str,
    ) -> SceneHandle:
        """启动或恢复 splatfacto 训练。

        Args:
            scene_data:      经 prepare_scene() 处理后的 SceneData。
            config:          训练配置（合并 _DEFAULT_CONFIG）。
            checkpoint_dir:  nerfstudio checkpoint 落盘目录。

        Returns:
            SceneHandle；is_complete=True 若训练正常结束，False 若被中断。
        """
        cfg = {**_DEFAULT_CONFIG, **config}
        ckpt_dir = Path(checkpoint_dir)

        # 若已有 checkpoint，获取 resume 路径
        resume_dir = self._find_latest_checkpoint_dir(ckpt_dir)

        # 构建 ns-train 命令
        cmd = self._build_ns_train_cmd(scene_data, cfg, ckpt_dir, resume_dir)

        if self.verbose:
            print(f"[Reconstructor] 启动训练：{scene_data.scene_id}")
            print(f"  命令：{' '.join(cmd)}")
            if resume_dir:
                print(f"  Resume from：{resume_dir}")

        is_complete = False
        last_step = self.get_latest_checkpoint_step(ckpt_dir)

        try:
            result = subprocess.run(cmd, check=True, text=True)
            is_complete = True
            last_step = cfg["max_num_iterations"]
        except subprocess.CalledProcessError as e:
            if self.verbose:
                print(f"[Reconstructor] 训练中断（exit code {e.returncode}）：{scene_data.scene_id}")
            # 读取中断时最新的 step
            last_step = self.get_latest_checkpoint_step(ckpt_dir)
        except KeyboardInterrupt:
            if self.verbose:
                print(f"[Reconstructor] 训练被用户中断：{scene_data.scene_id}")
            last_step = self.get_latest_checkpoint_step(ckpt_dir)

        return SceneHandle(
            scene_id=scene_data.scene_id,
            checkpoint_dir=str(ckpt_dir),
            output_dir=scene_data.output_dir,
            is_complete=is_complete,
            last_step=last_step,
        )

    def save_checkpoint(self, scene_handle: SceneHandle, path: str | Path) -> Path:
        """在 path 处创建指向 checkpoint_dir 的软链接（或复制目录）。"""
        dst = Path(path)
        src = Path(scene_handle.checkpoint_dir)
        if not src.exists():
            raise FileNotFoundError(f"checkpoint_dir 不存在：{src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            dst.unlink() if dst.is_symlink() else None
        try:
            dst.symlink_to(src.resolve())
        except OSError:
            # 跨文件系统不支持软链接时复制
            import shutil
            shutil.copytree(src, dst, dirs_exist_ok=True)
        return dst

    def load_checkpoint(self, path: str | Path) -> SceneHandle:
        """从 checkpoint 目录恢复 SceneHandle（不启动训练）。"""
        ckpt_dir = Path(path)
        last_step = self.get_latest_checkpoint_step(ckpt_dir)
        # 尝试从目录名推断 scene_id
        scene_id = ckpt_dir.name
        return SceneHandle(
            scene_id=scene_id,
            checkpoint_dir=str(ckpt_dir),
            output_dir="",
            is_complete=False,      # 需要调用方自行判断
            last_step=last_step,
        )

    def is_trained(self, scene_data: SceneData) -> bool:
        """判断 scene 是否已完成训练（checkpoint 目录存在且有最终 step）。"""
        # 约定：完成后存在 nerfstudio_models/ 子目录（ns-train 产出）
        ckpt_dir = Path(scene_data.output_dir) / "checkpoints" / scene_data.scene_id
        return (ckpt_dir / "nerfstudio_models").exists()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_ns_train_cmd(
        self,
        scene_data: SceneData,
        cfg: dict,
        ckpt_dir: Path,
        resume_dir: Optional[Path],
    ) -> list[str]:
        """构建 ns-train 命令列表。"""
        ns_train = self._find_ns_train()
        data_dir = scene_data.output_dir
        method = cfg.get("method", "splatfacto")

        cmd = [
            ns_train, method,
            "--data", data_dir,
            "--output-dir", str(ckpt_dir),
            "--experiment-name", scene_data.scene_id,
            "--viewer.quit-on-train-completion", "True",
            f"--max-num-iterations={cfg['max_num_iterations']}",
            f"--pipeline.datamanager.train-num-images-to-sample-from={cfg['batch_size']}",
        ]

        # 每 N 步保存一次 checkpoint
        if cfg.get("save_checkpoint_every"):
            cmd += [f"--steps-per-save={cfg['save_checkpoint_every']}"]

        # Resume from last checkpoint
        if resume_dir is not None:
            cmd += ["--load-dir", str(resume_dir)]

        # nerfstudio transforms.json dataparser
        cmd += ["nerfstudio-data", "--data", data_dir]

        return cmd

    @staticmethod
    def _find_ns_train() -> str:
        """定位 ns-train 可执行文件路径。"""
        # 优先查找当前 Python 环境的 bin/
        python_bin = Path(sys.executable).parent
        ns_train = python_bin / "ns-train"
        if ns_train.exists():
            return str(ns_train)
        # 回退：直接用名称（依赖 PATH）
        return "ns-train"

    def _find_latest_checkpoint_dir(self, ckpt_dir: Path) -> Optional[Path]:
        """在 nerfstudio 的输出目录结构中找最新的 checkpoint 子目录。

        nerfstudio 输出结构：
            <ckpt_dir>/<scene_id>/<timestamp>/splatfacto/<timestamp>/nerfstudio_models/
        """
        if not ckpt_dir.exists():
            return None
        # 递归找所有 nerfstudio_models 目录
        nerfstudio_model_dirs = list(ckpt_dir.rglob("nerfstudio_models"))
        if not nerfstudio_model_dirs:
            return None
        # 取修改时间最新的
        latest = max(nerfstudio_model_dirs, key=lambda p: p.stat().st_mtime)
        return latest
