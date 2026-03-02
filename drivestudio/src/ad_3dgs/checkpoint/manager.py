"""CheckpointManager — ICheckpointManager 的 JSON 后端实现。

职责：统一管理各 Stage 的进度与 checkpoint 路径，支持 OOM/崩溃后从断点恢复。

存储格式：单个 JSON 文件（默认 data/checkpoints/registry.json），结构：
    {
        "version": 1,
        "stages": {
            "<stage_id>": {
                "<scene_id>": {
                    "<chunk_id>": {
                        "status": "pending|running|complete",
                        "checkpoint_path": "/path/to/ckpt",
                        "state": {...},      # 任意 stage 状态
                        "updated_at": 1234567890.0
                    }
                }
            }
        }
    }

线程安全：单进程内使用，不加锁（Phase 6 分布式时可升级为 SQLite 后端）。
幂等：register_stage / mark_complete 可重复调用，不破坏一致性。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class ResumePoint:
    """从 CheckpointManager 查询到的断点信息。"""
    stage_id: str
    scene_id: str
    chunk_id: str
    checkpoint_path: Optional[str]    # None 表示无可用 checkpoint（从头开始）
    state: dict[str, Any]             # 上次保存的 stage 状态（如已完成帧数等）


# ---------------------------------------------------------------------------
# ICheckpointManager 抽象接口（轻量版，Phase 5.1 可扩展）
# ---------------------------------------------------------------------------

class CheckpointManager:
    """基于 JSON 文件的断点管理器。

    Args:
        registry_path: JSON 文件路径，默认 data/checkpoints/registry.json。
    """

    _CHUNK_DEFAULT = "__default__"

    def __init__(self, registry_path: str | Path = "data/checkpoints/registry.json") -> None:
        self._path = Path(registry_path)
        self._data: dict = self._load()

    # ------------------------------------------------------------------
    # 读写接口
    # ------------------------------------------------------------------

    def register_stage(
        self,
        stage_id: str,
        scene_id: str,
        state: dict[str, Any],
        chunk_id: str = _CHUNK_DEFAULT,
        checkpoint_path: Optional[str] = None,
    ) -> None:
        """注册或更新 stage/scene/chunk 的运行状态（status=running）。

        幂等：多次调用以最后一次为准。
        """
        entry = self._get_entry(stage_id, scene_id, chunk_id)
        entry["status"] = "running"
        entry["state"] = state
        if checkpoint_path is not None:
            entry["checkpoint_path"] = checkpoint_path
        entry["updated_at"] = time.time()
        self._save()

    def mark_complete(
        self,
        stage_id: str,
        scene_id: str,
        chunk_id: str = _CHUNK_DEFAULT,
        checkpoint_path: Optional[str] = None,
    ) -> None:
        """将 stage/scene/chunk 标记为完成（status=complete）。"""
        entry = self._get_entry(stage_id, scene_id, chunk_id)
        entry["status"] = "complete"
        if checkpoint_path is not None:
            entry["checkpoint_path"] = checkpoint_path
        entry["updated_at"] = time.time()
        self._save()

    def is_complete(
        self,
        stage_id: str,
        scene_id: str,
        chunk_id: str = _CHUNK_DEFAULT,
    ) -> bool:
        """判断 stage/scene/chunk 是否已完成。"""
        stages = self._data.get("stages", {})
        entry = stages.get(stage_id, {}).get(scene_id, {}).get(chunk_id, {})
        return entry.get("status") == "complete"

    def get_last_incomplete(
        self,
        stage_id: str,
        scene_id: Optional[str] = None,
    ) -> Optional[ResumePoint]:
        """返回最近一次未完成的 stage/scene/chunk。

        Args:
            stage_id:  Stage 名称，如 "stage2_recon"。
            scene_id:  若指定，只查询该 scene；否则查询所有 scene。

        Returns:
            ResumePoint，若全部完成或无记录则返回 None。
        """
        stages = self._data.get("stages", {})
        stage_entries = stages.get(stage_id, {})

        scenes_to_check = [scene_id] if scene_id else list(stage_entries.keys())

        for sid in scenes_to_check:
            chunks = stage_entries.get(sid, {})
            for chunk_id, entry in chunks.items():
                if entry.get("status") != "complete":
                    return ResumePoint(
                        stage_id=stage_id,
                        scene_id=sid,
                        chunk_id=chunk_id,
                        checkpoint_path=entry.get("checkpoint_path"),
                        state=entry.get("state", {}),
                    )
        return None

    def get_checkpoint_path(
        self,
        stage_id: str,
        scene_id: str,
        chunk_id: str = _CHUNK_DEFAULT,
    ) -> Optional[str]:
        """返回 stage/scene/chunk 已存储的 checkpoint 路径（不存在则 None）。"""
        stages = self._data.get("stages", {})
        entry = stages.get(stage_id, {}).get(scene_id, {}).get(chunk_id, {})
        return entry.get("checkpoint_path")

    def get_all_scenes(self, stage_id: str) -> list[str]:
        """返回该 stage 下所有 scene_id 列表（有任何记录的）。"""
        return list(self._data.get("stages", {}).get(stage_id, {}).keys())

    def clear_completed(self, scene_id: str) -> None:
        """删除 scene_id 下所有 stage 中已完成的 chunk 记录（可选，回收空间）。"""
        for stage_entries in self._data.get("stages", {}).values():
            if scene_id in stage_entries:
                stage_entries[scene_id] = {
                    k: v for k, v in stage_entries[scene_id].items()
                    if v.get("status") != "complete"
                }
        self._save()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_entry(self, stage_id: str, scene_id: str, chunk_id: str) -> dict:
        """获取或创建 stage/scene/chunk 的记录字典（原地修改，返回引用）。"""
        stages = self._data.setdefault("stages", {})
        scenes = stages.setdefault(stage_id, {})
        chunks = scenes.setdefault(scene_id, {})
        if chunk_id not in chunks:
            chunks[chunk_id] = {
                "status": "pending",
                "checkpoint_path": None,
                "state": {},
                "updated_at": time.time(),
            }
        return chunks[chunk_id]

    def _load(self) -> dict:
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                try:
                    d = json.load(f)
                    if d.get("version") != 1:
                        raise ValueError(f"不支持的 registry 版本：{d.get('version')}")
                    return d
                except (json.JSONDecodeError, ValueError):
                    # 损坏的 registry：重新初始化（下次写入时覆盖）
                    return {"version": 1, "stages": {}}
        return {"version": 1, "stages": {}}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
