# 本地环境（2080S + conda / ROS）

Phase 0.3：环境与数据准备。本文说明 **ROS（系统级）** 与 **conda（本项目 Python）** 的关系及安装步骤。

---

## 一、为什么 ROS 和 conda 是两套东西？

| 用途 | 安装方式 | 说明 |
|------|----------|------|
| **nuscenes2bag 转换**（nuScenes → ROS Bag） | **系统级 ROS**（apt 安装） | nuscenes2bag 是 C++ 的 ROS 包，需要 `rosrun`、catkin 编译、系统里的 ROS 环境；一般不放进 conda。 |
| **本仓库 Python 代码**（读 Bag、3DGS、渲染、写 Bag 等） | **conda 环境** | Phase 1 起用 Python 读/写 Bag（可用 `rosbags` 库，无需本机跑 ROS）；Phase 2 需要 nerfstudio。用 conda 隔离依赖、版本统一。 |

因此：**先在本机装好系统级 ROS**（用于运行 `scripts/download_and_convert_data.sh`），**再建一个 conda 环境**跑本项目的 Python 代码。不必、也不建议把「完整 ROS 桌面」装进 conda。

---

## 二、安装 ROS（系统级，用于转换脚本）

- **Ubuntu 20.04 (focal)**：安装 **ROS Noetic**（下面命令中已是 noetic）。
- **Ubuntu 18.04 (bionic)**：将下面 `noetic` 改为 **melodic**。
- **Ubuntu 22.04 (jammy)**：官方未提供 Noetic；建议用 **Docker 跑 Ubuntu 20.04 + ROS Noetic** 做转换，或在一台 20.04 机器/WSL2 的 20.04 镜像里安装。本机 22.04 仍可用 conda 跑本项目 Python 代码。

### 2.1 安装步骤（在 Ubuntu 终端执行）

需要 **sudo** 与网络。下面是分步命令，不是单条「一键」指令，建议逐行执行并观察输出：

```bash
# 添加 ROS 源与密钥
sudo sh -c 'echo "deb http://packages.ros.org/ros/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/ros-latest.list'
curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc | sudo apt-key add -
sudo apt update

# 安装 ROS Noetic 桌面版（含 rviz、rqt，便于后续需要时用）
sudo apt install -y ros-noetic-desktop

# 每次新开终端要用 ROS 时需执行：
source /opt/ros/noetic/setup.bash
```

若只需最小依赖（不包含 GUI），可改为：`sudo apt install -y ros-noetic-ros-base`。

### 2.2 安装 nuscenes2bag（catkin 编译）

ROS 装好后，编译 nuscenes2bag：

```bash
source /opt/ros/noetic/setup.bash
mkdir -p ~/catkin_ws/src
cd ~/catkin_ws/src
git clone https://github.com/clynamen/nuscenes2bag.git
cd ~/catkin_ws
catkin_make
source devel/setup.bash
```

之后每次要运行转换脚本前，先执行：

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
```

再运行 `./scripts/download_and_convert_data.sh ...`。

### 2.3 为什么没有在脚本里自动装 ROS？

- ROS 通过 **apt** 安装，需要 **sudo** 和正确的 **Linux 发行版**（如 Ubuntu）；当前环境可能是无 sudo 的沙箱或非 Ubuntu，无法保证一条命令在所有机器上成功。
- 安装会改动系统路径和依赖，适合由你在本机终端**手动执行一次**；文档中已给出完整命令，可直接复制执行。

---

## 三、conda 环境（本项目 Python）

用于 Phase 1 起的 **Python 代码**（读/写 Log、后续 3DGS、渲染等）。与 ROS 并行存在：**日志转换可在独立环境中做，其它用 conda**。

### 3.1 创建环境与验证（在 Ubuntu 终端执行）

1. **在项目根目录创建环境**  

```bash
cd /home/luosx/3dgs          # 换成你本机的项目路径
conda env create -f environments/conda_env.yaml -n 3dgs
```

> 如提示找不到 `conda`，先安装 Miniconda/Anaconda 并确保 `conda` 在 PATH 中。

2. **验证环境是否创建成功**  

```bash
conda env list | grep 3dgs   # 应该能看到名为 3dgs 的环境
```

3. **在 3dgs 环境中验证 Python 与依赖**（不必手动 `activate`，可用 `conda run`）：  

```bash
conda run -n 3dgs python -c "import sys; print('python', sys.version)"
conda run -n 3dgs python -c "import rosbags; print('rosbags-ok')"
```

4. **在 3dgs 环境中安装本项目（可编辑模式）**  

```bash
conda run -n 3dgs bash scripts/setup_env.sh
```

执行成功后，`3dgs` 环境中即可 `import ad_3dgs`（项目包名）并运行后续代码。日常开发时，你也可以使用常规方式激活环境：

```bash
conda activate 3dgs
```

### 3.2 依赖说明

- **Phase 1**：读/写 Bag 可用纯 Python 库 `rosbags`（无需本机安装 ROS），在 conda 中安装即可。
- **Phase 2**：nerfstudio 在 conda 中单独安装（见环境文档或 `conda_env.yaml` 注释）；2080S 8G 显存需注意配置。
- **ROS**：不需要在 conda 里装 ROS；转换 nuScenes → Bag 时在**已 source ROS 的终端**里运行 `download_and_convert_data.sh` 即可。

---

## 四、推荐工作流

1. **本机一次性**：按第二节安装 ROS Noetic + nuscenes2bag（catkin 编译）。
2. **转换数据时**：开一个终端，`source` 两个 setup.bash，运行 `download_and_convert_data.sh`，得到 `data/output/*.bag`。
3. **日常开发**：`conda activate 3dgs`，在项目里跑 Python（Reader/Writer、pipeline 等）；与是否 source ROS 无关。

这样「环境与数据准备」就齐了：系统 ROS 负责转换，conda 负责本仓库代码。
