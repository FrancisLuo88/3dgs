# Phase 0 子计划：环境与数据准备

> **状态**：Phase 0 已完成（2026-02）。本文档保留历史决策过程，任务表已更新为实际产出。  
> 注：本文档早期版本以 ROS Bag 为主输入格式；后架构演进为 **MCAP 主格式**，以下任务表与主架构文档保持一致。

---

## 任务与产出对照（已完成）

| 序号 | 任务 | 产出 | 状态 |
|------|------|------|------|
| 0.1 | 选定 nuScenes，用 nuscenes2mcap 转换为 **MCAP**（主格式） | `data/input/` 下 10 个 scene 的 `.mcap` 文件 | ✅ |
| 0.2 | 定义「输入日志」规范（MCAP 为主，ROS Bag 为可选备用） | `docs/specs/input_bag_schema.md`（含真实 channel/schema 与字段说明） | ✅ |
| 0.3 | 本地 2080S + conda 环境；主流程无需 ROS | `docs/env/local_setup.md`、`environments/conda_env.yaml`、`scripts/setup_env.sh` | ✅ |

---

## 历史子计划（已归档，仅供参考）

以下为 Phase 0 开始前规划的 6 步实施方案，均已执行完毕。

### 步骤 1：补全「数据集与工具」文档（对应 0.1 前半）

| 项目 | 内容 |
|------|------|
| **做什么** | 填写 `docs/data/dataset_and_tools.md`：选定 nuScenes 为首选；写入 nuscenes2mcap 的仓库链接、安装方式、命令行用法。 |
| **为什么** | 0.1 要求「选定数据集」并「搭建转换脚本」；先固化文档，后续脚本与 0.2 的 schema 都以此为准。 |
| **状态** | ✅ 已完成，见 `docs/data/dataset_and_tools.md` |

---

### 步骤 2：实现「下载与转换」脚本骨架（对应 0.1 后半）

| 项目 | 内容 |
|------|------|
| **做什么** | 转换脚本骨架 + `scripts/check_nuscenes_data.py`（检查 nuScenes 目录完整性）；nuscenes2mcap 通过 Docker 运行，不依赖本机 ROS。 |
| **为什么** | 产出「可复现的输入 MCAP」需要一条可执行的路径。 |
| **状态** | ✅ 已完成，MCAP 已在 `data/input/` |

---

### 步骤 3：定义「输入日志」规范文档（对应 0.2）

| 项目 | 内容 |
|------|------|
| **做什么** | 填写 `docs/specs/input_bag_schema.md`，包含 MCAP channel 命名、消息类型、时间戳来源、CameraCalibration 字段。 |
| **为什么** | Phase 1 的 Reader/Writer 和后续 Stage 都依赖「输入长什么样」。 |
| **状态** | ✅ 已完成并用实测数据更新（真实 channel 名与字段值） |

---

### 步骤 4：本地环境文档（对应 0.3 文档部分）

| 项目 | 内容 |
|------|------|
| **做什么** | 填写 `docs/env/local_setup.md`：Python 版本要求、conda 环境、mcap/rosbags 安装。ROS 仅在需要 Bag 输出时使用，非主流程依赖。 |
| **状态** | ✅ 已完成 |

---

### 步骤 5：conda 环境与一键安装脚本（对应 0.3 脚本部分）

| 项目 | 内容 |
|------|------|
| **做什么** | `environments/conda_env.yaml`（含 mcap-protobuf-support、rosbags）+ `scripts/setup_env.sh`（pip install -e .）。 |
| **状态** | ✅ 已完成；mcap-protobuf-support 已安装到 3dgs conda 环境 |

---

### 步骤 6：更新 Phase 0 与开发计划索引

| 项目 | 内容 |
|------|------|
| **做什么** | 在 `docs/architecture/development_plan.md` 中增加各 Phase 完成标准，并更新本文档为「已完成」状态。 |
| **状态** | ✅ 已完成，见 `development_plan.md` |

---

## 不在此阶段做的事情（历史记录）

- **不**实现 Reader/Writer 代码（属 Phase 1）。
- **不**编写 Timeline 序列化格式（已在 Phase 0 完成时补充，见 `docs/specs/timeline_format.md`）。
- **不**在 conda_env 中默认加入 nerfstudio 的完整依赖（Phase 2 前安装）。
