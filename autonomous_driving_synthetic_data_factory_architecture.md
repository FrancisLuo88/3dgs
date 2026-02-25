# 自动驾驶合成数据工厂 — 核心架构与开发计划

**角色**：系统架构师  
**目标**：构建从晴天 ROS Bag → 3DGS 重建 → 雨夜重渲染 + 动态虚拟车辆 → 时间戳严格对齐的 ROS Bag 输出流水线，支持 7 路相机同步播放与断点续传。

---

## 一、推荐开源自动驾驶数据集（无现成数据时的选择）

| 数据集 | 相机数 | 频率 | 格式 | 天气/场景 | 与需求的匹配度 | 备注 |
|--------|--------|------|------|-----------|----------------|------|
| **nuScenes** | 6 (CAM_FRONT, FRONT_LEFT/RIGHT, BACK_LEFT/RIGHT, BACK) | 12 Hz | 自有格式 → **nuscenes2rosbag** 转 ROS Bag | 多天气含晴天 | ⭐⭐⭐⭐ 首选 | 无 LiDAR 子集可选；6 路可扩展为 7 路或按 6 路设计 pipeline |
| **Waymo Open Dataset (E2E)** | 8 (前/左前/右前/左/右/后/左后/右后) | 10 Hz | TFRecord → 自写转 ROS Bag | 多场景 | ⭐⭐⭐⭐ | 取 7 路即可；需额外做 TFRecord → ROS Bag 转换 |
| **KITTI Raw** | 2 (灰度+彩色) / 4 (部分) | 10 Hz | 图像+标定 → **kitti2bag** 转 ROS Bag | 晴天为主 | ⭐⭐ | 相机路数少，不适合 7 路播放 |
| **MCD** | 立体相机等，非 7 路 RGB | — | ROS Bag / MCAP | 校园多场景 | ⭐⭐ | 传感器配置与“7 路相机”不一致 |

**结论与建议**  
- **首选**：**nuScenes** + 工具 **nuscenes2rosbag**（或 nuscenes2mcap）得到多相机、带时间戳的 ROS Bag；按 6 路设计 pipeline，预留 1 路扩展或与产品约定“6 路亦可”。  
- **备选**：**Waymo Open Dataset (E2E)**，8 路取 7 路，自研 TFRecord → ROS Bag 转换器，时间戳从 Frame 元数据解析并严格保留。

---

## 二、核心架构图

### 2.1 总体数据流与阶段划分

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        自动驾驶合成数据工厂 — 数据流与阶段                                  │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐     ┌─────────────────────────────────────────────────────────────────┐
  │  Input      │     │                     PROCESSING PIPELINE                           │
  │  ROS Bag    │     │                                                                   │
  │  (7路相机   │────▶│  Stage 1          Stage 2              Stage 3        Stage 4     │
  │  +时间戳)   │     │  解析与校验    →   per-scene 3DGS    →  雨夜重渲染  →  虚拟车植入   │
  └──────────────┘     │  (时间戳抽取)     (nerfstudio/3DGS)    (天气+光照)    (5车+碰撞体)  │
                       │       │                  │                    │            │     │
                       │       ▼                  ▼                    ▼            ▼     │
                       │  ┌─────────┐       ┌─────────┐          ┌─────────┐  ┌─────────┐ │
                       │  │ Checkpoint│       │ Checkpoint│         │ Checkpoint│  │ Checkpoint│ │
                       │  │ Manager   │       │ Manager   │         │ Manager   │  │ Manager   │ │
                       │  └────┬────┘       └────┬────┘          └────┬────┘  └────┬────┘ │
                       │       │                  │                    │            │     │
                       │       └──────────────────┴────────────────────┴────────────┘     │
                       │                              │                                    │
                       │                    ┌─────────▼─────────┐                          │
                       │                    │  Global Checkpoint │  ◀── 显存 OOM / 崩溃时   │
                       │                    │  & Resume Manager  │     从断点恢复，不重跑   │
                       │                    └─────────┬─────────┘                          │
                       └──────────────────────────────┼────────────────────────────────────┘
                                                      │
  ┌──────────────┐                                     ▼
  │  Output      │     ┌─────────────────────────────────────────────────────────────────┐
  │  ROS Bag     │◀────│  Stage 5: 重打包与时间戳对齐                                        │
  │  (7路+对齐)  │     │  - 按原 Bag 时间戳严格写 msg                                       │
  └──────────────┘     │  - 流式写 + 内存上限控制                                           │
                       └─────────────────────────────────────────────────────────────────┘
```

### 2.2 内存管理策略（显存 + 主机内存）

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                            MEMORY MANAGEMENT STRATEGY                                    │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  GPU (RTX 2080S 8GB)                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │ • 3DGS 训练：固定 batch / 每帧点数上限；单 scene 训练时其余 scene 不驻留显存          │   │
│  │ • 渲染：按「帧窗口」渲染（如 50 帧一批），写盘后释放；禁止全序列一次性进显存            │   │
│  │ • 显存预算：训练 ~6GB 峰值预留，渲染 ~5GB；超限前主动 checkpoint 并释放大对象         │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                          │
│  Host (RAM + Disk)                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │ • Bag 读取：流式按 topic/time 迭代，不整包加载到内存；时间戳索引常驻（小）            │   │
│  │ • 中间结果：每 stage 输出落盘（图像序列/相机参数/3D 资源）；仅当前 chunk 在内存        │   │
│  │ • 输出 Bag：缓冲 N 条 msg 再写盘，控制内存上限；时间戳严格按原索引写入                 │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 断点续传机制（OOM / 崩溃不从头再来）

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                      CHECKPOINT & RESUME MECHANISM                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  粒度：Scene / Chunk / Frame 三级                                                        │
│                                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │
│  │ Scene A     │    │ Scene B     │    │ Scene C     │    │ ...         │               │
│  │ [done]      │───▶│ [running]   │───▶│ [pending]   │───▶│             │               │
│  └─────────────┘    └──────┬──────┘    └─────────────┘    └─────────────┘               │
│                            │                                                             │
│                            ▼                                                             │
│  Per-Stage 状态落盘：                                                                     │
│  • Stage1: scene_id → 解析后的 frame_index + 时间戳列表 + 相机外参 (JSON/msgpack)         │
│  • Stage2: scene_id → nerfstudio ckpt 路径 + 已完成的 scene 列表                         │
│  • Stage3: scene_id + chunk_id → 已渲染帧区间 [t_start, t_end] + 输出路径                 │
│  • Stage4: scene_id + chunk_id → 已植入虚拟车的帧区间 + 资源版本                         │
│  • Stage5: 已写入的 last_timestamp + 输出 bag 路径                                       │
│                                                                                          │
│  恢复策略：                                                                               │
│  1. 启动时读取 Global Checkpoint Registry（如 JSON/SQLite）；                             │
│  2. 若上次在 Stage2 某 scene 训练中 OOM：从该 scene 的 last_ckpt 调用 nerfstudio 续训；   │
│  3. 若在 Stage3 渲染中 OOM：跳过已完成的 chunk，从下一 chunk 继续渲染；                    │
│  4. 所有 stage 幂等：重复运行已完成的 scene/chunk 可覆盖或跳过，不破坏一致性。            │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心 Python 抽象类（≥5）

以下抽象类定义**接口与职责**，不包含具体实现代码，便于多实现（本地 2080S / 云端 A100）与测试替身替换。

---

### 1. `IRosBagReader`（输入层）

- **职责**：从 ROS Bag（或 MCAP）中按时间戳有序读取多路相机数据，不将整包加载进内存。
- **核心方法**：
  - `get_topic_names() -> List[str]`
  - `get_timeline() -> Timeline`（或等价：时间戳序列 + 每帧各 topic 的 msg 引用/路径）
  - `iter_frames(t_start, t_end, camera_topic_ids) -> Iterator[Frame]`
  - `get_camera_info(topic_id) -> CameraInfo`
- **约束**：迭代器为流式；Timeline 可持久化为断点用。

---

### 2. `ISceneReconstructor`（3D 重建层）

- **职责**：以多视角图像 + 相机内外参为输入，训练 3DGS（或等价神经辐射场），并支持从 checkpoint 恢复。
- **核心方法**：
  - `prepare_scene(frames: Sequence[Frame], camera_infos) -> SceneHandle`
  - `train(scene_handle, config, checkpoint_dir) -> TrainingResult`（内部支持 resume）
  - `save_checkpoint(scene_handle, path) -> Path`
  - `load_checkpoint(path) -> SceneHandle`
- **约束**：显存超限前应能保存 checkpoint；训练配置暴露 max_gpu_memory 或等价参数。

---

### 3. `IWeatherRenderer`（重渲染层）

- **职责**：在给定 3D 场景与相机轨迹下，将「晴天」重渲染为「雨夜」等目标天气（光照 + 雨/雾等效果）。
- **核心方法**：
  - `set_weather_model(weather_type: str, params: dict) -> None`
  - `render_frame(camera_pose, camera_intrinsics, scene_handle, timestamp) -> RenderedFrame`
  - `render_sequence(poses_and_intrinsics, scene_handle, timestamps, chunk_size) -> Iterator[RenderedFrame]`
- **约束**：按 chunk 渲染并 yield，避免整序列进显存；支持从 chunk 边界断点续传。

---

### 4. `IVirtualObjectInserter`（虚拟物体层）

- **职责**：在已渲染图像（或 3D 空间）中植入带碰撞体积的动态虚拟车辆，保证多视角一致与遮挡关系。
- **核心方法**：
  - `add_vehicle(vehicle_spec: VehicleSpec, trajectory: Trajectory) -> ObjectId`
  - `set_vehicles(vehicles: List[Tuple[VehicleSpec, Trajectory]]) -> None`（如固定 5 车）
  - `composite_frame(rendered_frame, timestamp, object_states) -> CompositeFrame`
  - `get_collision_volumes() -> List[CollisionVolume]`（可选，供仿真/评测）
- **约束**：轨迹与时间戳对齐；输出与原时间戳一一对应。

---

### 5. `IRosBagWriter`（输出层）

- **职责**：将合成后的多路图像与元数据按**原 Bag 时间戳严格对齐**写回 ROS Bag。
- **核心方法**：
  - `open(path, topic_schema) -> None`
  - `write_frame(timestamp: rospy.Time, camera_id: str, image, camera_info) -> None`
  - `write_sync_point(timestamp, frame_dict) -> None`（一次写入多路一帧，保证同步）
  - `close() -> None`
- **约束**：时间戳必须来自原始 Timeline，不允许重排或插值导致错位；写盘缓冲有上限。

---

### 6. `ICheckpointManager`（断点与恢复）

- **职责**：统一管理各 Stage 的进度与 checkpoint 路径，支持 OOM/崩溃后从断点恢复。
- **核心方法**：
  - `register_stage(stage_id, scene_id, chunk_id, state: dict) -> None`
  - `get_last_incomplete(stage_id) -> Optional[ResumePoint]`
  - `mark_complete(stage_id, scene_id, chunk_id) -> None`
  - `get_checkpoint_path(stage_id, scene_id) -> Optional[Path]`
  - `clear_completed(scene_id) -> None`（可选，回收空间）
- **约束**：单进程或分布式下同一 pipeline run 使用同一 registry（如文件/DB）；幂等与可重入。

---

## 四、详细开发计划（结构化、分阶段）

### Phase 0：环境与数据准备（1–2 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 0.1 | 选定数据集（nuScenes 或 Waymo），搭建下载与转换脚本（→ ROS Bag） | 可复现的「输入 Bag」样本（含 6/7/8 路相机 + 时间戳） | 无 |
| 0.2 | 定义「输入 Bag」规范：topic 命名、消息类型、时间戳来源、相机 ID 与标定存储方式 | 文档 + 示例 Bag 的 schema | 0.1 |
| 0.3 | 本地 2080S + Docker/conda 环境：nerfstudio、ROS、Python 版本统一 | 环境文档 + 一键脚本 | 无 |

---

### Phase 1：输入/输出与时间戳基线（2–3 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 1.1 | 实现 `IRosBagReader`：流式读取、Timeline 构建、按帧迭代 | 模块 + 单元测试（用 0.1 的 Bag） | 0.2 |
| 1.2 | 实现 `IRosBagWriter`：按给定时间戳写多路图像，校验回放时间戳一致 | 模块 +  roundtrip 测试（读→写→再读比对） | 0.2 |
| 1.3 | 定义「内部帧」数据结构（Frame / RenderedFrame / CompositeFrame）与时间戳贯穿规则 | 类型定义 + 文档 | 1.1 |
| 1.4 | 实现 7 路（或 6 路）同步播放的验证脚本（如 rqt_bag / 自写小工具） | 可演示「输入 Bag 同步播放」 | 1.1, 1.2 |

---

### Phase 2：3DGS 重建与断点（3–4 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 2.1 | 实现 `ISceneReconstructor` 的 nerfstudio/3DGS 适配：从 Bag 解析到 nerfstudio 数据格式 | 单 scene 可训练 | 1.1, 0.3 |
| 2.2 | 集成 nerfstudio checkpoint：训练循环内定期 save + 显存超限前 save；支持 `load` 后 resume | 可恢复的训练 run | 2.1 |
| 2.3 | 显存预算与降级策略：2080S 8G 下 max_gpu_memory、batch、图像分辨率等可配置；文档化 | 配置模板 + 文档 | 2.1 |
| 2.4 | 多 scene 划分策略：按时间或按距离切 scene；每 scene 独立 checkpoint 目录 | 多 scene 训练脚本 | 2.2 |
| 2.5 | 单元/集成测试：单 scene 训练 → 中断 → resume → 导出 3DGS 一致 | 自动化测试 | 2.2 |

---

### Phase 3：雨夜重渲染与分块（2–3 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 3.1 | 实现 `IWeatherRenderer`：基于 3DGS 的渲染接口；雨夜 shader/后处理或现成天气模型接入 | 单帧/短序列雨夜输出 | 2.1 |
| 3.2 | 按 chunk 渲染与 yield：chunk_size 可配置；渲染完一个 chunk 即释放显存并可选写盘 | 流式渲染 API | 3.1 |
| 3.3 | 渲染阶段 checkpoint：记录已完成的 (scene_id, chunk_id)；恢复时跳过已完成 chunk | 与 2.x 同风格断点 | 见下节 Checkpoint |
| 3.4 | 质量与性能：雨夜效果验收；2080S 下 chunk 大小与 FPS 满足「3× 数据时长」约束 | 性能报告 + 参数表 | 3.2 |

---

### Phase 4：虚拟车辆植入（2–3 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 4.1 | 定义 `VehicleSpec` 与 `Trajectory`（时间戳对齐）；设计 5 车轨迹生成或从脚本/配置读取 | 数据结构和示例轨迹 | 1.3 |
| 4.2 | 实现 `IVirtualObjectInserter`：3D 放置 + 多视角光栅化或 alpha 合成，保证遮挡一致 | 单帧/短序列合成 | 3.1, 4.1 |
| 4.3 | 碰撞体积：定义碰撞体数据结构；在 3D 或 2D 投影下可查询（供后续仿真/评测） | 接口 + 简单实现 | 4.2 |
| 4.4 | 与 Timeline 严格对齐：每帧 timestamp 对应固定 object_states；写入前校验 | 集成测试 | 4.2, 1.3 |

---

### Phase 5：全局断点与流水线编排（2–3 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 5.1 | 实现 `ICheckpointManager`：Registry 存储（JSON/SQLite）、ResumePoint 解析、按 stage/scene/chunk 查询 | 可用的 CheckpointManager | Phase 2–4 的 checkpoint 约定 |
| 5.2 | 流水线编排器：顺序执行 Stage1→…→Stage5；每 stage 前检查 ResumePoint，从断点继续 | 单机 DAG 执行器 | 5.1, 1.1–4.4 |
| 5.3 | OOM 与异常处理：捕获显存不足/进程崩溃；退出前写入当前进度；下次启动自动 resume | 鲁棒性验收 | 5.2 |
| 5.4 | 端到端测试：小规模 Bag → 完整 pipeline → 输出 Bag → 7 路同步播放验证 | E2E 测试 + 演示 | 5.2, 1.4 |

---

### Phase 6：性能与生产化（2–3 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 6.1 | 性能调优：2080S 下整段 pipeline 时间 ≤ 3× 数据时长；参数表与调优记录 | 性能报告 | 5.4 |
| 6.2 | 云端 A100 适配：配置切换（显存、batch、chunk）、无状态 worker 或分布式 checkpoint | 云端运行文档与脚本 | 5.2 |
| 6.3 | 可观测性：各 stage 耗时、显存峰值、checkpoint 次数；日志与简单 metrics | 运维文档 | 5.2 |
| 6.4 | 文档与交付：架构图、抽象类说明、部署手册、数据集与转换说明 | 交付包 | 全阶段 |

---

## 五、架构原则小结

- **数据流**：单向 pipeline（Input → 解析 → 3DGS → 重渲染 → 虚拟车 → 输出 Bag），每阶段输入/输出落盘，便于断点与重跑。
- **内存**：GPU 按 scene/chunk 滚动使用；Host 流式读 Bag、分块写 Bag，不整包进内存。
- **断点**：Scene/Chunk 粒度 + Global Checkpoint Registry；OOM 或崩溃后从 last incomplete 恢复，不从头再来。
- **时间戳**：从输入 Bag 抽取的 Timeline 贯穿全 pipeline；输出 Bag 严格按原时间戳写入，保证 7 路同步播放一致。
- **抽象**：5+ 抽象类隔离 IO、重建、渲染、合成、写出与断点管理，便于本地/云端与不同 3DGS/天气实现替换。

以上为不包含具体实现代码的架构与计划，可直接用于评审与任务拆解；实现时可按需将抽象类再拆为更多接口（如 `ITimeline`、`IResourceStore`）以贴合具体技术栈。
