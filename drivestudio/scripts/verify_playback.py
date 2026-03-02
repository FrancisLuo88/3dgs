#!/usr/bin/env python3
"""6 路同步播放验证脚本（Phase 1.4 / 5.4）

功能：
  - 读取 MCAP，构建 Timeline
  - 对每个 TimelineEntry，统计 6 路时间戳最大偏差
  - 打印汇总报告（帧数、完整帧率、偏差分布）
  - 超出阈值时标记警告

用法：
  python scripts/verify_playback.py <input.mcap> [--threshold-ms 50] [--verbose]

退出码：
  0  所有帧均在阈值内（或无超阈值帧）
  1  存在超阈值帧（需要人工检查）
  2  文件不存在或解析错误
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from collections import Counter


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证 MCAP 中 6 路相机帧的时间戳同步质量"
    )
    parser.add_argument("mcap", help="待验证的 MCAP 文件路径")
    parser.add_argument(
        "--threshold-ms",
        type=float,
        default=50.0,
        help="时间戳偏差阈值（毫秒），超出则报告警告（默认 50）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印每个超阈值 entry 的详细信息",
    )
    args = parser.parse_args()

    mcap_path = Path(args.mcap)
    if not mcap_path.exists():
        print(f"[ERROR] 文件不存在：{mcap_path}", file=sys.stderr)
        return 2

    threshold_ns = int(args.threshold_ms * 1_000_000)

    # 动态导入（确保 src 在 sys.path）
    sys.path.insert(0, str(_repo_root() / "src"))
    try:
        from ad_3dgs.io.reader_mcap import LogReaderMcap
    except ImportError as e:
        print(f"[ERROR] 无法导入 ad_3dgs：{e}", file=sys.stderr)
        print("       请先运行 `pip install -e .` 或激活 conda 环境", file=sys.stderr)
        return 2

    print(f"验证文件：{mcap_path}")
    print(f"阈值：{args.threshold_ms} ms")
    print()

    try:
        with LogReaderMcap(mcap_path) as reader:
            timeline = reader.get_timeline()
            topics = reader.get_topic_names()
    except Exception as e:
        print(f"[ERROR] 读取 MCAP 失败：{e}", file=sys.stderr)
        return 2

    total = len(timeline)
    n_cameras = len(topics)
    print(f"Topic 数：{n_cameras}")
    print(f"Topic 列表：")
    for t in topics:
        print(f"  {t}")
    print(f"\nTimeline entries 总数：{total}")
    print(f"时间范围：{timeline.start_ns} → {timeline.end_ns} ns")
    duration_s = (timeline.end_ns - timeline.start_ns) / 1e9
    print(f"时长：{duration_s:.2f} 秒")
    print()

    # --- 统计 ---
    frame_counts: Counter = Counter()     # entry 中有几路相机
    max_deviations_ns: list[int] = []     # 每个 entry 中最大时间偏差（ns）
    warn_entries: list[tuple] = []        # (index, timestamp_ns, max_dev_ns, missing)

    for i, entry in enumerate(timeline.entries):
        n = len(entry.frames)
        frame_counts[n] += 1

        if n > 1:
            ts_vals = [ref.timestamp_ns for ref in entry.frames.values()]
            max_dev = max(ts_vals) - min(ts_vals)
        elif n == 1:
            max_dev = 0
        else:
            max_dev = 0

        max_deviations_ns.append(max_dev)

        missing = set(topics) - set(entry.frames.keys())
        has_violation = max_dev > threshold_ns
        if has_violation:
            warn_entries.append((i, entry.timestamp_ns, max_dev, missing))

    # --- 汇总 ---
    full_entries = frame_counts[n_cameras]
    full_ratio = full_entries / total if total > 0 else 0.0
    avg_dev_ms = (sum(max_deviations_ns) / len(max_deviations_ns) / 1e6) if max_deviations_ns else 0
    max_dev_ms = max(max_deviations_ns) / 1e6 if max_deviations_ns else 0

    print("=== 同步质量报告 ===")
    print(f"完整帧（{n_cameras} 路齐全）：{full_entries}/{total}  ({full_ratio:.1%})")
    print("各路数分布：")
    for k in sorted(frame_counts.keys(), reverse=True):
        print(f"  {k} 路：{frame_counts[k]} frames")
    print(f"\n时间戳偏差统计（各 entry 中 6 路最大差）：")
    print(f"  平均：{avg_dev_ms:.3f} ms")
    print(f"  最大：{max_dev_ms:.3f} ms")

    thresholds = [1, 5, 10, 20, 50, 100]
    print(f"  偏差分布（超出各阈值的 entry 数）：")
    for thr in thresholds:
        n_over = sum(1 for d in max_deviations_ns if d > thr * 1_000_000)
        print(f"    > {thr:3d} ms：{n_over} frames  ({n_over/total:.1%})")

    if warn_entries:
        print(f"\n[WARN] 超出阈值 {args.threshold_ms} ms 的 entry：{len(warn_entries)} 个")
        if args.verbose:
            for idx, ts, dev, missing in warn_entries[:20]:
                print(f"  entry {idx:4d}  ts={ts}  max_dev={dev/1e6:.1f} ms  missing={missing}")
            if len(warn_entries) > 20:
                print(f"  ... 还有 {len(warn_entries)-20} 个（使用 --verbose 查看前 20）")
    else:
        print(f"\n[OK] 所有 entry 时间戳偏差均在阈值 {args.threshold_ms} ms 内")

    print()

    # 退出码
    if warn_entries:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
