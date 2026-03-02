#!/usr/bin/env bash
# nuScenes → ROS Bag 转换（Phase 0.1）
# 说明：本脚本不负责从网络下载 nuScenes，仅将本机已有的 nuScenes 数据根目录转换为 ROS Bag。
# 依赖：已安装 nuscenes2bag（ROS 包）。数据需先在 https://www.nuscenes.org/ 下载并解压。详见 docs/data/dataset_and_tools.md
set -euo pipefail

# -----------------------------------------------------------------------------
# 默认值与用法
# -----------------------------------------------------------------------------
NUSCENES_VERSION="${NUSCENES_VERSION:-v1.0-mini}"
NUSCENES_JOBS="${NUSCENES_JOBS:-4}"

usage() {
  echo "用法: $0 --dataroot <nuScenes 数据根目录> --out <输出目录> [选项]"
  echo ""
  echo "必选:"
  echo "  --dataroot DIR   nuScenes 数据根目录（含 samples、版本元数据等）"
  echo "  --out DIR        输出目录，生成的 .bag 写入此处"
  echo ""
  echo "可选:"
  echo "  --version VER    元数据版本，默认: v1.0-mini"
  echo "  --scene_number N 仅转换指定 scene（如 0061）"
  echo "  --jobs N         并行 scene 数，默认: 4（全量转换时有效）"
  echo ""
  echo "也可通过环境变量传入: NUSCENES_DATAROOT, NUSCENES_OUT, NUSCENES_VERSION, NUSCENES_SCENE_NUMBER, NUSCENES_JOBS"
  echo "详见: docs/data/dataset_and_tools.md"
  exit 1
}

# -----------------------------------------------------------------------------
# 解析参数（环境变量可被命令行覆盖）
# -----------------------------------------------------------------------------
DATAROOT="${NUSCENES_DATAROOT:-}"
OUT="${NUSCENES_OUT:-}"
SCENE_NUMBER=""
JOBS="$NUSCENES_JOBS"
VERSION="$NUSCENES_VERSION"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataroot)  DATAROOT="$2"; shift 2 ;;
    --out)       OUT="$2";      shift 2 ;;
    --version)   VERSION="$2";  shift 2 ;;
    --scene_number) SCENE_NUMBER="$2"; shift 2 ;;
    --jobs)      JOBS="$2";     shift 2 ;;
    -h|--help)   usage ;;
    *) echo "未知参数: $1"; usage ;;
  esac
done

# -----------------------------------------------------------------------------
# 必选参数检查
# -----------------------------------------------------------------------------
if [[ -z "$DATAROOT" || -z "$OUT" ]]; then
  echo "错误: 必须指定 --dataroot 与 --out（或设置 NUSCENES_DATAROOT、NUSCENES_OUT）"
  usage
fi

if [[ ! -d "$DATAROOT" ]]; then
  echo "错误: 数据根目录不存在: $DATAROOT"
  echo "请先下载 nuScenes 数据并解压，参见 https://www.nuscenes.org/ 与 docs/data/dataset_and_tools.md"
  exit 1
fi

mkdir -p "$OUT"

# -----------------------------------------------------------------------------
# 检查 nuscenes2bag 是否可用
# -----------------------------------------------------------------------------
if ! command -v rosrun &>/dev/null; then
  echo "错误: 未找到 rosrun，请先安装并 source ROS 环境（如 source /opt/ros/noetic/setup.bash）。"
  echo ""
  echo "安装 nuscenes2bag 后，在运行本脚本前请执行: source /path/to/catkin_ws/devel/setup.bash"
  echo "详见: docs/data/dataset_and_tools.md"
  exit 1
fi

if ! rospack find nuscenes2bag &>/dev/null; then
  echo "错误: 未找到 ROS 包 nuscenes2bag。"
  echo ""
  echo "请按以下步骤安装:"
  echo "  1. 进入 catkin workspace:  cd /path/to/catkin_ws/src"
  echo "  2. 克隆: git clone https://github.com/clynamen/nuscenes2bag.git"
  echo "  3. 编译: cd /path/to/catkin_ws && catkin_make  # 或 catkin build"
  echo "  4. 加载环境: source devel/setup.bash"
  echo "  5. 再运行本脚本"
  echo ""
  echo "完整说明: docs/data/dataset_and_tools.md"
  exit 1
fi

# -----------------------------------------------------------------------------
# 调用 nuscenes2bag
# -----------------------------------------------------------------------------
echo "dataroot=$DATAROOT"
echo "out=$OUT"
echo "version=$VERSION"
echo "jobs=$JOBS"
if [[ -n "$SCENE_NUMBER" ]]; then
  echo "scene_number=$SCENE_NUMBER"
fi
echo ""

if [[ -n "$SCENE_NUMBER" ]]; then
  rosrun nuscenes2bag nuscenes2bag \
    --scene_number "$SCENE_NUMBER" \
    --dataroot "$DATAROOT" \
    --out "$OUT" \
    --version "$VERSION"
else
  rosrun nuscenes2bag nuscenes2bag \
    --dataroot "$DATAROOT" \
    --out "$OUT" \
    --version "$VERSION" \
    --jobs "$JOBS"
fi

echo ""
echo "完成。输出目录: $OUT"
