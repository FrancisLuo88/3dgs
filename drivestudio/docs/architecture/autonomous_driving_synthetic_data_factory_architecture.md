# 自动驾驶合成数据工厂 — 核心架构与开发计划

**角色**：系统架构师  
**目标**：构建从晴天**多路相机日志**（以 **MCAP** 为主输入，nuScenes2mcap 产出）→ 3DGS 重建 → 雨夜重渲染 + 动态虚拟车辆 → 时间戳严格对齐的合成结果；**输出**可为 MCAP，或经「MCAP → ROS Bag 转换」得到 ROS Bag，支持 6/7 路同步播放与断点续传。

---

## 一、推荐开源自动驾驶数据集（无现成数据时的选择）

| 数据集 | 相机数 | 频率 | 格式 | 天气/场景 | 与需求的匹配度 | 备注 |
|--------|--------|------|------|-----------|----------------|------|
| **nuScenes** | 6 (CAM_FRONT, FRONT_LEFT/RIGHT, BACK_LEFT/RIGHT, BACK) | 12 Hz | 自有格式 → **nuscenes2mcap** 转 MCAP（主流程） / **nuscenes2bag** 转 ROS Bag（备选） | 多天气含晴天 | ⭐⭐⭐⭐ 首选 | 无 LiDAR 子集可选；6 路可扩展为 7 路或按 6 路设计 pipeline |
| **Waymo Open Dataset (E2E)** | 8 (前/左前/右前/左/右/后/左后/右后) | 10 Hz | TFRecord → 自写转 MCAP / ROS Bag | 多场景 | ⭐⭐⭐⭐ | 取 7 路即可；需额外做 TFRecord → MCAP/ROS Bag 转换 |
| **KITTI Raw** | 2 (灰度+彩色) / 4 (部分) | 10 Hz | 图像+标定 → 自写转 MCAP / **kitti2bag** 转 ROS Bag | 晴天为主 | ⭐⭐ | 相机路数少，不适合 7 路播放 |
| **MCD** | 立体相机等，非 7 路 RGB | — | ROS Bag / MCAP | 校园多场景 | ⭐⭐ | 传感器配置与“7 路相机”不一致 |

**结论与建议**  
- **首选**：**nuScenes** + 工具 **nuscenes2mcap** 得到多相机、带时间戳的 **MCAP 日志**，作为 pipeline 内部的**主输入格式**；按 6 路设计 pipeline，预留 1 路扩展或与产品约定“6 路亦可”。  
- **备选**：如需要直接在 ROS 生态中使用，可在专用环境里使用 **nuscenes2bag** 先转 ROS Bag；或对 Waymo/其他数据集自写 TFRecord → MCAP/ROS Bag 转换器，时间戳从 Frame 元数据解析并严格保留。

---

## 二、核心架构图

### 2.1 总体数据流与阶段划分

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        自动驾驶合成数据工厂 — 数据流与阶段                                  │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐     ┌─────────────────────────────────────────────────────────────────┐
  │  Input Log  │     │                     PROCESSING PIPELINE                           │
  │  (MCAP 主   │     │                                                                   │
  │  ROS Bag 备)│────▶│  Stage 1          Stage 2              Stage 3        Stage 4     │
  └──────────────┘     │  解析与校验    →   per-scene 3DGS    →  雨夜重渲染  →  虚拟车植入   │
                       │  (时间戳抽取)     (nerfstudio/3DGS)    (天气+光照)    (5车+碰撞体)  │
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
  │  MCAP 或     │◀────│  Stage 5: 重打包与时间戳对齐（ILogWriter：主写 MCAP）               │
  │  ROS Bag     │     │  - 按原 Timeline 严格写；流式写 + 内存上限控制                      │
  └──────────────┘     └───────────────────────────────┬─────────────────────────────────┘
                                                        │
  ┌──────────────┐     ┌───────────────────────────────▼─────────────────────────────────┐
  │  ROS Bag     │◀────│  Stage 5b（可选）: MCAP → ROS Bag 转换                             │
  │  (需时再跑)  │     │  - 读合成结果 MCAP，按原时间戳写 ROS Bag；可在 20.04+ROS 环境执行   │
  └──────────────┘     └─────────────────────────────────────────────────────────────────┘
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
│  │ • Log 读取：流式按 topic/time 迭代（MCAP/Bag），不整包加载；时间戳索引常驻（小）      │   │
│  │ • 中间结果：每 stage 输出落盘（图像序列/相机参数/3D 资源）；仅当前 chunk 在内存        │   │
│  │ • 输出 Log：缓冲 N 条再写盘（主 MCAP），控制内存上限；时间戳严格按原索引写入           │   │
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

### 1. `ILogReader`（输入层，抽象 MCAP / ROS Bag）

- **职责**：从**多路相机日志**（MCAP 或 ROS Bag）中按时间戳有序读取，不将整包加载进内存；调用方不关心底层格式。
- **实现**：**`LogReaderMcap`**（主，基于 mcap/rosbags 等读 MCAP）、**`LogReaderRosBag`**（可选，基于 rosbags 读 .bag）。
- **核心方法**：
  - `get_topic_names() -> List[str]`（或 channel 名，统一抽象为 topic）
  - `get_timeline() -> Timeline`（时间戳序列 + 每帧各 topic 的 msg 引用/路径）
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

### 5. `ILogWriter`（输出层，抽象 MCAP / ROS Bag）

- **职责**：将合成后的多路图像与元数据按**原 Timeline 时间戳严格对齐**写回日志；格式可为 MCAP 或 ROS Bag，由实现决定。
- **实现**：**`LogWriterMcap`**（主，写 MCAP）、**`LogWriterRosBag`**（可选，写 .bag，或由「MCAP→ROS Bag 转换」阶段产出）。
- **核心方法**：
  - `open(path, topic_schema) -> None`
  - `write_frame(timestamp, camera_id: str, image, camera_info) -> None`（timestamp 为纳秒或 rospy.Time 抽象）
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
| 0.1 | 选定数据集（nuScenes），搭建下载与 **nuScenes→MCAP** 转换（nuscenes2mcap）；可选保留 nuScenes→ROS Bag 脚本（nuscenes2bag） | 可复现的「输入 **MCAP**」样本（含 6 路相机 + 时间戳）；可选 Bag 样本 | 无 |
| 0.2 | 定义「输入日志」规范：**MCAP** 与（可选）ROS Bag 的 topic/channel 命名、消息类型、时间戳来源、相机 ID 与标定 | 文档 + 示例 MCAP/Bag 的 schema | 0.1 |
| 0.3 | 本地 2080S + conda 环境：Python、nerfstudio 等；无需系统 ROS（主流程走 MCAP） | 环境文档 + conda 一键脚本 | 无 |

---

### Phase 1：输入/输出与时间戳基线（2–3 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 1.1 | 实现 **`ILogReader`**：流式读取、Timeline 构建、按帧迭代；**优先 MCAP 实现**，可选 ROS Bag 实现 | 模块 + 单元测试（用 0.1 的 MCAP） | 0.2 |
| 1.2 | 实现 **`ILogWriter`**：按给定时间戳写多路图像；**优先 MCAP 实现**，可选 Bag 实现；校验回放时间戳一致 | 模块 + roundtrip 测试（读→写→再读） | 0.2 |
| 1.3 | 定义「内部帧」数据结构（Frame / RenderedFrame / CompositeFrame）与时间戳贯穿规则 | 类型定义 + 文档 | 1.1 |
| 1.4 | 实现 6/7 路同步播放验证（MCAP 可用 Foxglove Studio 或自写工具；Bag 可用 rqt_bag） | 可演示「输入 MCAP/Bag 同步播放」 | 1.1, 1.2 |

---

### Phase 2：3DGS 重建与断点（3–4 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 2.1 | 实现 `ISceneReconstructor` 的 nerfstudio/3DGS 适配：从 **Log**（MCAP/Bag）解析到 nerfstudio 数据格式 | 单 scene 可训练 | 1.1, 0.3 |
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
| 5.4 | 端到端测试：小规模 MCAP → 完整 pipeline → 输出 MCAP（或 Bag）→ 6/7 路同步播放验证 | E2E 测试 + 演示 | 5.2, 1.4 |

---

### Phase 6：性能与生产化（2–3 周）

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 6.1 | 性能调优：2080S 下整段 pipeline 时间 ≤ 3× 数据时长；参数表与调优记录 | 性能报告 | 5.4 |
| 6.2 | 云端 A100 适配：配置切换（显存、batch、chunk）、无状态 worker 或分布式 checkpoint | 云端运行文档与脚本 | 5.2 |
| 6.3 | 可观测性：各 stage 耗时、显存峰值、checkpoint 次数；日志与简单 metrics | 运维文档 | 5.2 |
| 6.4 | 文档与交付：架构图、抽象类说明、部署手册、数据集与转换说明 | 交付包 | 全阶段 |
| **6.5** | **MCAP → ROS Bag 转换 Stage**：职责与实现（见下节）；在需交付 ROS Bag 时于 20.04+ROS 或容器中运行 | 转换脚本/模块 + 文档 | 5.4 |

---

## 五、MCAP → ROS Bag 转换 Stage（Stage 5b）职责与实现思路

当**下游必须使用 ROS Bag**（如既有工具链、仿真只认 .bag）时，在 pipeline 主输出 MCAP 之后增加本阶段，不改变主流程的「输入/内部/主输出均为 MCAP」设计。

- **职责**：
  - 输入：Stage 5 产出的**合成结果 MCAP**（多路图像 + 原 Timeline 时间戳）。
  - 输出：**ROS Bag**，topic 与消息类型符合 `docs/specs/input_bag_schema.md`（或单独「输出 Bag schema」）；**时间戳与 MCAP 中完全一致**，保证 6/7 路同帧同戳。
  - 运行环境：可在 **Ubuntu 20.04 + ROS Noetic** 或 **Docker 容器**内执行，避免在 22.04 上装 ROS1。
- **实现思路**：
  - 使用 **ILogReader** 的 MCAP 实现读取合成结果 MCAP，按 Timeline 迭代帧；
  - 使用 **rosbags** 或 **rosbag**（ROS 自带）写 .bag：将每帧多路图像按 `write_sync_point(timestamp, frame_dict)` 的语义写入对应 image + camera_info topic；
  - topic 命名与消息类型（sensor_msgs/Image、CameraInfo）与「输入 Bag 规范」对齐，便于下游复用同一套解析逻辑；
  - 可做成独立脚本（如 `scripts/convert_mcap_to_rosbag.py`）或 pipeline 的可选 Step，由配置决定是否在 Stage 5 之后执行。
- **与主 pipeline 的关系**：主 pipeline（Stage 1～5）**不依赖 ROS**，仅在需要 ROS Bag 时调用本阶段；本阶段可异步或离线跑，输入为已写盘的 MCAP 文件。

---

## 六、架构原则小结

- **数据流**：单向 pipeline（**输入 MCAP** → 解析 → 3DGS → 重渲染 → 虚拟车 → **输出 MCAP**）；可选 Stage 5b 将 MCAP 转为 ROS Bag。每阶段输入/输出落盘，便于断点与重跑。
- **内存**：GPU 按 scene/chunk 滚动使用；Host 流式读 Log（MCAP/Bag）、分块写 Log，不整包进内存。
- **断点**：Scene/Chunk 粒度 + Global Checkpoint Registry；OOM 或崩溃后从 last incomplete 恢复，不从头再来。
- **时间戳**：从输入 Log 抽取的 Timeline 贯穿全 pipeline；输出 MCAP（及可选 Bag）严格按原时间戳写入，保证 6/7 路同步播放一致。
- **抽象**：**ILogReader / ILogWriter** 统一 MCAP 与 Bag，实现层提供 **LogReaderMcap / LogWriterMcap**（主）与 **LogReaderRosBag / LogWriterRosBag**（可选）；其余抽象类隔离重建、渲染、合成与断点管理。

以上为不包含具体实现代码的架构与计划，可直接用于评审与任务拆解；实现时可按需将抽象类再拆为更多接口（如 `ITimeline`、`IResourceStore`）以贴合具体技术栈。
