# 自动驾驶合成数据工厂（3DGS）

从晴天**多路相机日志**（**MCAP** 为主输入，nuScenes2mcap）→ 3DGS 重建 → 雨夜重渲染 + 动态虚拟车辆 → 时间戳严格对齐的合成结果；输出 **MCAP**，可选经 Stage 5b 转为 **ROS Bag**。支持 6/7 路同步播放与断点续传。

### 3D Gaussian Splatting 实时渲染演示
<video width="800" controls autoplay muted loop>
  <source src="data/assets/videos_eval/full_set_40000_rgbs.mp4" type="video/mp4">
  你的浏览器不支持视频播放，请下载查看：[full_set_40000_rgbs.mp4](data/assets/videos_eval/full_set_40000_rgbs.mp4)
</video>

## 文档与架构

- **[架构与开发计划](docs/architecture/autonomous_driving_synthetic_data_factory_architecture.md)**：数据流、内存与断点、抽象类、Phase 0～6
- **[仓库结构说明](docs/architecture/repo_structure_proposal.md)**：目录与文档规范
- **规范与环境**：`docs/specs/`、`docs/env/`、`docs/ops/`、`docs/data/`

## 目录概览

| 目录 | 说明 |
|------|------|
| `docs/` | 架构、规范、环境、运维、数据集文档 |
| `config/` | 流水线、重建、场景划分配置模板 |
| `data/` | 输入/输出 Bag、checkpoints、中间结果（需 .gitignore 大文件） |
| `src/` | 源码：io、reconstruction、rendering、composition、checkpoint、pipeline |
| `scripts/` | 数据下载转换、一键运行、播放验证 |
| `tests/` | unit、integration、e2e |
| `environments/` | Dockerfile、conda 环境 |

## 快速开始

1. 环境：见 `docs/env/local_setup.md`（待补充）
2. 数据：使用 `scripts/download_and_convert_data.sh` 或见 `docs/data/dataset_and_tools.md`
3. 运行：`scripts/run_pipeline.py`（实现后）

## 开发阶段

按 [开发计划](docs/architecture/development_plan.md) 的 Phase 0～6 推进。
