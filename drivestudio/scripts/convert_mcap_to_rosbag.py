#!/usr/bin/env python3
"""
Stage 5b：MCAP → ROS Bag 转换。
读入合成结果 MCAP，按原时间戳写出 ROS Bag，供下游 ROS 工具使用。
可在 Ubuntu 20.04 + ROS 或 Docker 中运行；主 pipeline 不依赖 ROS。
"""
# TODO: 使用 ILogReader(MCAP) 读 + rosbags / rosbag 写 .bag；topic 与 docs/specs/input_bag_schema.md 对齐
