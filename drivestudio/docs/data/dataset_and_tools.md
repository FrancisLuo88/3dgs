# 数据集与转换工具

本 pipeline **已选定 nuScenes 数据集**；**主输入格式为 MCAP**（由 nuscenes2mcap 产出），无需本机安装 ROS。若需 ROS Bag，可选用 nuscenes2bag（需 Ubuntu 20.04 + ROS）或由 pipeline 输出 MCAP 后再经「MCAP → ROS Bag」转换。以下为数据集获取与**主路径：nuScenes → MCAP** 说明。

---

## 一、选定数据集：nuScenes

| 项目 | 说明 |
|------|------|
| **官网** | [https://www.nuscenes.org/](https://www.nuscenes.org/) |
| **相机** | 6 路：CAM_FRONT, CAM_FRONT_LEFT, CAM_FRONT_RIGHT, CAM_BACK_LEFT, CAM_BACK_RIGHT, CAM_BACK |
| **频率** | 约 12 Hz，带时间戳 |
| **天气/场景** | 多天气含晴天，适合做「晴天→雨夜」重渲染 |
| **使用约定** | 本仓库按 **6 路相机** 设计 pipeline，与 nuScenes 一致；后续若需 7 路可扩展或与产品约定「6 路亦可」。 |

**获取数据**

- **数据需在 [nuScenes 官网](https://www.nuscenes.org/) 自行下载并解压**。转换由 **nuscenes2mcap**（主，见下节）或 **nuscenes2bag**（备选，需 ROS）完成，脚本见 `scripts/`；均不会从网络拉取数据。
- 需在官网注册并同意条款，下载需登录。
- **开发/调试**建议先用 **nuScenes mini**（v1.0-mini，体量小、下载快）。
- 完整版可选 v1.0 / v2.0 等，按需选择 `--version`。

**解压说明**

- 解压命令示例：`tar -xzf v1.0-mini.tgz -C /path/to/data/input`。若出现 “Cannot change ownership” 报错，可加 `--no-same-owner`（文件仍会解出，仅不保留原压缩包内的属主），例如：`tar -xzf v1.0-mini.tgz -C /path/to/data/input --no-same-owner`。

**目录结构约定**

- 解压后，**数据根目录**（下称 `dataroot`）内应包含：
  - `samples/`：各相机图像（如 `samples/CAM_FRONT/`、`samples/CAM_BACK/` 等 6 路）
  - `v1.0-mini/`（或对应版本）：元数据 `.json` 等
  - `maps/`、`sweeps/`：可选（部分工具需要）

---

## 二、转换工具（主：MCAP；备选：ROS Bag）

### 2.1 首选工具：nuscenes2mcap（nuScenes → MCAP）

本 pipeline **主输入为 MCAP**，不依赖本机 ROS。使用 **nuscenes2mcap** 将 nuScenes 转为 `.mcap`，Stage 1 用 `ILogReader` 的 MCAP 实现流式读取。

| 项目 | 说明 |
|------|------|
| **仓库** | [foxglove/nuscenes2mcap](https://github.com/foxglove/nuscenes2mcap) |
| **输出** | MCAP（`.mcap`） |
| **依赖** | Python 3 + Docker，无需 ROS |

**安装与运行**

- 将 nuScenes 数据解压到项目 `data/` 下（如 `data/nuscenes/` 含 samples、v1.0-mini 等）。
- 使用项目内 Docker 构建并转换（示例）：
  ```bash
  git clone https://github.com/foxglove/nuscenes2mcap.git
  cd nuscenes2mcap
  # 将 nuScenes 解压到 data/；然后：
  ./convert_mini_scenes.sh
  # 或：docker run -v $(pwd)/data:/data -v $(pwd)/output:/output mcap_converter python3 convert_to_mcap.py --data-dir /data --output-dir /output
  ```
- 输出 `.mcap` 放入本仓库 `data/input/`，供 pipeline 使用。详见 [nuscenes2mcap README](https://github.com/foxglove/nuscenes2mcap)。

### 2.2 备选工具：nuscenes2bag（nuScenes → ROS Bag）

| 项目 | 说明 |
|------|------|
| **仓库** | [clynamen/nuscenes2bag](https://github.com/clynamen/nuscenes2bag) |
| **输出** | ROS 1 Bag（`.bag`） |
| **依赖** | ROS Melodic/Kinetic，catkin 编译 |

**安装**

- 将仓库克隆到 catkin workspace 的 `src/` 下，然后编译：
  ```bash
  cd /path/to/catkin_ws/src
  git clone https://github.com/clynamen/nuscenes2bag.git
  cd /path/to/catkin_ws
  catkin_make   # 或 catkin build
  source devel/setup.bash
  ```

**命令行参数**

| 参数 | 含义 |
|------|------|
| `--dataroot` | nuScenes 数据根目录（含 samples、sweeps、maps 及版本子目录） |
| `--out` | 输出目录，生成的 `.bag` 会写在此处 |
| `--version` | 元数据版本子目录名，默认 `v1.0-mini` |
| `--scene_number` | 可选，只转换指定 scene（如 `0061`） |
| `--jobs` | 可选，并行处理的 scene 数量（如 `4`） |

**示例：单 scene（例如 0061）**

```bash
rosrun nuscenes2bag nuscenes2bag \
  --scene_number 0061 \
  --dataroot /path/to/nuscenes_mini_meta_v1.0/ \
  --out /path/to/nuscenes_bags/
```

输出会落在 `--out` 目录下（如 `61.bag`，以 scene 编号命名）。

**示例：全量 mini 数据集（多 scene 并行）**

```bash
rosrun nuscenes2bag nuscenes2bag \
  --dataroot /path/to/nuscenes_mini_meta_v1.0/ \
  --out /path/to/nuscenes_bags/ \
  --jobs 4
```

**示例：其他版本（如 v2.0）**

```bash
rosrun nuscenes2bag nuscenes2bag \
  --dataroot /path/to/nuscenes_data_v2.0/ \
  --version v2.0 \
  --out /path/to/nuscenes_bags/ \
  --jobs 4
```

转换得到的 Bag 内含图像、相机标定、TF 等；时间戳由工具从 nuScenes 元数据写入。若用 Bag 作输入，需符合 **输入日志规范**（见 `docs/specs/input_bag_schema.md`）。

### 2.3 可选：nuscenes2rosbag（带 IMU）

若需要 **IMU** 与相机同包：

- 仓库：[zhijie-yang/nuscenes2rosbag](https://github.com/zhijie-yang/nuscenes2rosbag)
- 用法与 nuscenes2bag 类似，同为 ROS 包，catkin 编译后 `rosrun` 调用。

本 pipeline 当前阶段**仅依赖多路相机 + 时间戳**，IMU 为可选扩展。

---

## 三、与本 pipeline 的对接

- **Stage 1 输入**：**主路径**读入由 **nuscenes2mcap** 生成的 **MCAP**，通过 `ILogReader` 的 MCAP 实现流式按时间戳迭代多路相机；可选读入 nuscenes2bag 生成的 ROS Bag（`ILogReader` 的 Bag 实现）。
- **输入规范**：topic/channel 命名、消息类型、时间戳来源、相机 ID 与标定见 **`docs/specs/input_bag_schema.md`**（MCAP 与 Bag 的约定）。
- **数据准备**：MCAP 由 nuscenes2mcap（Docker）产出后放入 `data/input/`；Bag 由 **`scripts/download_and_convert_data.sh`**（需 ROS 环境）产出，可选。
