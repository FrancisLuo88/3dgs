# 自动驾驶合成数据工厂 — 仓库结构与文档规范（草案）

本文档根据 `autonomous_driving_synthetic_data_factory_architecture.md` 的规划，定义**规范的文档结构**与**整个仓库的文件/文件夹结构**。在您同意后再创建对应分层目录与占位文件。

---

## 一、规范的文档结构（文档放在哪）

| 文档类型 | 放置位置 | 说明 |
|----------|----------|------|
| 架构与规划 | `docs/architecture/` | 核心架构图、阶段划分、抽象类说明、开发计划（可引用根目录的 architecture.md 或迁入此处） |
| 输入/输出规范 | `docs/specs/` | 输入 Bag schema、Timeline 序列化格式、输出 Bag 与 7 路同步约定 |
| 环境与部署 | `docs/env/` | 本地 2080S / 云端 A100 环境说明、Docker、依赖版本 |
| 运维与可观测 | `docs/ops/` | 日志、metrics、断点与恢复操作手册 |
| 数据集与工具 | `docs/data/` | 数据集选用、nuscenes2bag / nuscenes2mcap 用法与链接（可摘录自架构 doc） |
| 项目总览 | 根目录 `README.md` | 项目简介、快速开始、目录说明、开发阶段对应关系 |

---

## 二、整个仓库文件结构框图

```
3dgs/                                    # 仓库根目录
├── README.md                            # 项目总览、快速开始、目录说明（含指向 docs 的链接）
├── pyproject.toml                       # Python 项目与依赖（或 requirements.txt）
├── .gitignore                           # 忽略 data/、checkpoints、大文件等
│
├── docs/                                # 所有正式文档
│   ├── architecture/                   # 架构与规划
│   │   ├── README.md                    # 索引
│   │   ├── autonomous_driving_synthetic_data_factory_architecture.md   # 架构规划主文档
│   │   ├── repo_structure_proposal.md   # 本仓库结构草案（即当前 REPO_STRUCTURE_PROPOSAL.md 迁入）
│   │   └── development_plan.md         # 开发计划表（可从主架构 doc 拆出）
│   ├── specs/                           # 输入/输出规范
│   │   ├── input_bag_schema.md          # 输入 Bag topic、消息类型、时间戳
│   │   └── timeline_format.md           # Timeline 序列化格式（Phase 0.3）
│   ├── env/                             # 环境与部署
│   │   ├── local_setup.md               # 本地 2080S + conda/Docker
│   │   └── cloud_a100.md                # 云端 A100 配置与脚本
│   ├── ops/                             # 运维
│   │   └── checkpoint_and_resume.md     # 断点续传操作说明
│   └── data/                            # 数据集与工具
│       └── dataset_and_tools.md         # 数据集选用、nuscenes2bag/mcap 链接与用法
│
├── config/                              # 配置模板（不包含敏感信息）
│   ├── pipeline.yaml                    # 流水线全局参数（chunk_size、stage 开关等）
│   ├── reconstruction.yaml              # 3DGS/nerfstudio 相关（batch、max_gpu_memory、分辨率）
│   └── scene_split.yaml                 # 场景划分策略（按时间/距离）
│
├── data/                                # 数据目录（.gitignore，仅保留占位与 schema）
│   ├── .gitkeep                         # 保证目录被 git 跟踪
│   ├── input/                           # 输入 ROS Bag 或索引路径配置
│   │   └── .gitkeep
│   ├── output/                          # 输出 ROS Bag
│   │   └── .gitkeep
│   ├── checkpoints/                     # Global Checkpoint Registry 与各 stage 状态
│   │   └── .gitkeep
│   └── intermediate/                   # 中间结果（按 scene/chunk 落盘）
│       ├── stage1_timeline/             # Stage1 解析结果（Timeline、相机外参）
│       ├── stage2_3dgs/                 # Stage2 各 scene 的 3DGS 模型/ckpt
│       ├── stage3_rendered/             # Stage3 雨夜渲染图像序列
│       └── stage4_composite/            # Stage4 合成后图像（可选，或直接进 Stage5）
│           └── .gitkeep
│
├── src/                                 # 源代码（按架构分层）
│   ├── __init__.py
│   ├── types/                           # 公共数据类型（Frame、Timeline、CameraInfo、VehicleSpec…）
│   │   ├── __init__.py
│   │   └── (data classes / TypedDict)
│   ├── io/                              # 输入/输出层（ILogReader / ILogWriter，MCAP 主、Bag 可选）
│   │   ├── __init__.py
│   │   ├── reader.py                    # ILogReader 抽象
│   │   ├── reader_mcap.py               # LogReaderMcap 实现
│   │   ├── reader_rosbag.py             # LogReaderRosBag 实现
│   │   ├── writer.py                    # ILogWriter 抽象
│   │   ├── writer_mcap.py               # LogWriterMcap 实现
│   │   └── writer_rosbag.py             # LogWriterRosBag 实现
│   ├── reconstruction/                  # 3D 重建层
│   │   ├── __init__.py
│   │   └── scene_reconstructor.py      # ISceneReconstructor（nerfstudio/3DGS 适配）
│   ├── rendering/                       # 重渲染层
│   │   ├── __init__.py
│   │   └── weather_renderer.py          # IWeatherRenderer（雨夜等）
│   ├── composition/                    # 虚拟物体层
│   │   ├── __init__.py
│   │   └── virtual_inserter.py         # IVirtualObjectInserter（5 车 + 碰撞体）
│   ├── checkpoint/                      # 断点与恢复
│   │   ├── __init__.py
│   │   └── manager.py                  # ICheckpointManager（Registry、ResumePoint）
│   └── pipeline/                        # 流水线编排
│       ├── __init__.py
│       ├── stages.py                    # Stage1～Stage5 单步逻辑
│       └── orchestrator.py              # 顺序执行 + 断点恢复
│
├── scripts/                             # 可执行脚本（非库代码）
│   ├── download_and_convert_data.sh    # nuScenes→ROS Bag（可选，需 ROS）；主路径用 nuscenes2mcap→MCAP
│   ├── run_pipeline.py                  # 一键运行流水线（调 orchestrator）
│   ├── verify_playback.py               # 6/7 路同步播放验证（Phase 1.4 / 5.4）
│   └── convert_mcap_to_rosbag.py       # Stage 5b：MCAP → ROS Bag 转换（可选）
│
├── tests/                               # 测试
│   ├── __init__.py
│   ├── unit/                            # 单元测试（各接口与工具函数）
│   │   ├── test_reader.py
│   │   ├── test_writer.py
│   │   └── ...
│   ├── integration/                     # 集成测试（如 读→写 roundtrip、单 scene 训练 resume）
│   │   └── ...
│   └── e2e/                             # 端到端（小 Bag → 全 pipeline → 输出 Bag → 播放验证）
│       └── ...
│
└── environments/                        # 环境定义（可选）
    ├── Dockerfile                       # 本地/CI 用
    └── conda_env.yaml                   # conda 环境
```

---

## 三、各层目录与架构对应关系

| 目录 | 对应架构内容 | 开发阶段 |
|------|----------------|----------|
| `docs/` | 文档规范、架构图、开发计划、规范说明 | Phase 0～6 |
| `config/` | 显存/batch/chunk/场景划分等可配置项 | Phase 0.3, 2.3, 6.2 |
| `data/` | 输入 Bag、输出 Bag、Checkpoint、中间落盘 | 全 pipeline |
| `src/types/` | Frame、RenderedFrame、CompositeFrame、Timeline、CameraInfo、VehicleSpec、Trajectory | Phase 1.3, 4.1 |
| `src/io/` | IRosBagReader、IRosBagWriter | Phase 1.1, 1.2 |
| `src/reconstruction/` | ISceneReconstructor | Phase 2.x |
| `src/rendering/` | IWeatherRenderer | Phase 3.x |
| `src/composition/` | IVirtualObjectInserter | Phase 4.x |
| `src/checkpoint/` | ICheckpointManager | Phase 5.1 |
| `src/pipeline/` | Stage1～5、Orchestrator | Phase 5.2, 5.3 |
| `scripts/` | 数据准备、一键运行、播放验证 | Phase 0.1, 1.4, 5.4 |
| `tests/` | 单元、集成、E2E | Phase 1～6 |

---

## 四、说明与约定

- **不创建实际代码实现**：仅创建分层文件夹与占位文件（如 `__init__.py`、`.gitkeep`），或按您同意后的范围创建。
- **data/**：建议加入 `.gitignore`，仅提交 `data/**/.gitkeep` 或少量 schema 示例，避免大文件入库。
- **架构与仓库结构文档**：`autonomous_driving_synthetic_data_factory_architecture.md` 与 `REPO_STRUCTURE_PROPOSAL.md` 均放入 `docs/architecture/`，根目录 `README.md` 中提供「架构与开发计划」「仓库结构说明」的链接，便于从总览进入。
- **命名**：目录与文件均英文、小写、下划线，与常见 Python 项目一致。

请您审阅上述**文档结构**与**仓库文件结构框图**。若同意，我将按此创建全部分层文件夹及必要的占位文件（如 `.gitkeep`、空 `__init__.py`）；若有增删改需求，请直接指出后再执行创建。
