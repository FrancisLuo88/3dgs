#!/usr/bin/env bash
# 在 conda 环境 3dgs 中执行：安装本项目为可编辑包
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -e .
echo ""
echo "下一步："
echo "  - 转换 nuScenes → ROS Bag：在已 source ROS 的终端运行 scripts/download_and_convert_data.sh"
echo "  - 安装 ROS / nerfstudio 说明：见 docs/env/local_setup.md"
