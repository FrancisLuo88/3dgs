# 开发计划表

开发计划详见 [autonomous_driving_synthetic_data_factory_architecture.md](autonomous_driving_synthetic_data_factory_architecture.md) 第四节「详细开发计划」。

- Phase 0：环境与数据准备
- Phase 1：输入/输出与时间戳基线
- Phase 2：3DGS 重建与断点
- Phase 3：雨夜重渲染与分块
- Phase 4：虚拟车辆植入
- Phase 5：全局断点与流水线编排
- Phase 6：性能与生产化

---

## Phase 完成标准

每个 Phase 进入下一阶段前，须满足以下条件。

---

### Phase 0 ✅（已完成，2026-02）

| 条件 | 验证方式 |
|------|---------|
| `data/input/` 下有至少 1 个 `.mcap` 文件（nuScenes→MCAP 转换可复现） | `ls data/input/*.mcap` |
| `docs/specs/input_bag_schema.md` 中 MCAP channel 名与字段来自实测（非猜测） | 文档中存在真实 topic 名如 `/CAM_FRONT/image_rect_compressed` |
| `conda_env.yaml` 包含 `mcap-protobuf-support` 与 `rosbags`，且 conda 环境可 `import mcap` | `conda run -n 3dgs python -c "import mcap"` 无报错 |
| `docs/specs/timeline_format.md` 定义了 Timeline 的字段与 JSON 序列化格式 | 文档非空，含 `FrameRef`、`TimelineEntry`、`Timeline` 结构说明 |
| `src/ad_3dgs/types/__init__.py` 定义了 `Frame`、`Timeline`、`CameraInfo` 等基础类型 | `from ad_3dgs.types import Timeline, Frame, CameraInfo` 无报错 |
| `docs/env/local_setup.md` 描述了 conda 环境搭建步骤，且主流程不要求本机 ROS | 文档存在且非空 |

---

### Phase 1（进行中目标）

| 条件 | 验证方式 |
|------|---------|
| `LogReaderMcap` 可流式读取 `data/input/` 中的 MCAP，返回 `Timeline` 和 `MultiCameraFrame` | 单元测试 `tests/unit/test_reader.py` 全部通过 |
| `Timeline` 可序列化为 JSON 并反序列化，内容一致 | `tests/unit/test_reader.py` roundtrip 测试通过 |
| `LogWriterMcap` 可按给定时间戳写多路图像，回读时时间戳与原始一致（精度：纳秒） | `tests/unit/test_writer.py` roundtrip 测试通过 |
| 6 路同步播放验证可在 Foxglove Studio 中演示（读输入 MCAP 或写出的输出 MCAP） | `scripts/verify_playback.py` 无报错，或 Foxglove 截图存档 |
| `src/ad_3dgs/types/__init__.py` 中类型可供 Reader/Writer 完整使用（无 `Any` 占位） | 代码审查 |

---

### Phase 2

| 条件 | 验证方式 |
|------|---------|
| `ISceneReconstructor` nerfstudio 适配：单 scene 可从 MCAP Timeline 解析帧并启动训练 | 脚本运行无报错，nerfstudio 输出 checkpoint 目录 |
| 训练过程可从任意 checkpoint 恢复，输出模型与从头训练一致 | 集成测试：中断→恢复→导出，输出 checkpoint hash 一致 |
| 2080S 8G 显存下单 scene 训练不 OOM（max_gpu_memory 已配置） | `config/reconstruction.yaml` 存在相关配置，实测通过 |
| 多 scene 划分脚本可将一段 Timeline 切为多个 scene，各自独立 checkpoint | `scripts/run_pipeline.py --stage 2` 可并行或顺序处理多 scene |

---

### Phase 3

| 条件 | 验证方式 |
|------|---------|
| `IWeatherRenderer` 可按 chunk 流式渲染，不一次性将全序列图像进显存 | 代码审查：`render_sequence` 使用 yield + chunk_size |
| 单帧雨夜渲染输出可视觉验收（人工检查或 SSIM 基线） | 验收截图或测试报告存档 |
| 渲染阶段有 checkpoint：恢复时跳过已完成的 chunk | 集成测试：中断后从 chunk 边界恢复 |

---

### Phase 4

| 条件 | 验证方式 |
|------|---------|
| `IVirtualObjectInserter` 可在渲染帧中植入至少 1 辆虚拟车，多视角遮挡关系正确 | 人工目视验收（多路相机对同一虚拟车的投影一致） |
| 虚拟车轨迹与 Timeline 时间戳严格对齐（每帧 timestamp 对应固定 object_states） | 集成测试：逐帧校验 object_states.timestamp == frame.timestamp_ns |
| 碰撞体积接口可查询（`get_collision_volumes()` 返回非空列表） | 单元测试 |

---

### Phase 5

| 条件 | 验证方式 |
|------|---------|
| `ICheckpointManager` 可存储/查询 stage/scene/chunk 粒度进度，JSON 或 SQLite 持久化 | 单元测试 |
| 端到端流水线：小规模 MCAP（1 scene）→ 全 pipeline → 输出 MCAP，可在 Foxglove 播放 | `scripts/run_pipeline.py` 全量运行无报错 |
| OOM 模拟：手动杀进程后重启，pipeline 从断点继续，不重跑已完成的 scene/chunk | 手工验收或自动化测试 |

---

### Phase 6

| 条件 | 验证方式 |
|------|---------|
| 2080S 下完整 pipeline 处理时长 ≤ 3× 数据时长（性能目标） | 性能报告存档 |
| 云端 A100 配置可切换（config 覆盖），不需改代码 | `config/pipeline.yaml` 存在 `device: a100` 相关配置项 |
| 各 stage 耗时、显存峰值可在日志中查询 | 运行日志示例存档 |
| `README.md` 与 `docs/` 可指导新成员从零复现整个流程 | 文档审查 |
