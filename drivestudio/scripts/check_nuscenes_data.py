#!/usr/bin/env python3
"""
检查 nuScenes 数据目录是否满足 nuscenes2mcap 转换所需条件。
用法:
  python scripts/check_nuscenes_data.py [数据根目录]
  或设置环境变量 NUSCENES_DATAROOT
若未指定，默认使用 项目根/data/input。
"""
from pathlib import Path
import json
import os
import sys


def main():
    repo_root = Path(__file__).resolve().parent.parent
    default_dataroot = repo_root / "data" / "input"
    dataroot = Path(os.environ.get("NUSCENES_DATAROOT", default_dataroot))
    if len(sys.argv) >= 2:
        dataroot = Path(sys.argv[1])

    if not dataroot.is_dir():
        print(f"[FAIL] 数据根目录不存在: {dataroot}")
        sys.exit(1)

    print(f"数据根目录: {dataroot}")
    print()

    checks = []

    # 1) 必要目录
    required_dirs = ["samples", "v1.0-mini", "can_bus", "maps"]
    for name in required_dirs:
        p = dataroot / name
        ok = p.is_dir()
        checks.append(("目录", name, p, ok))

    # 2) maps 子结构（nuscenes2mcap 报错指向 maps/expansion/<name>.json）
    maps_dir = dataroot / "maps"
    expansion_dir = maps_dir / "expansion"
    basemap_dir = maps_dir / "basemap"
    checks.append(("目录", "maps/expansion", expansion_dir, expansion_dir.is_dir()))
    checks.append(("目录", "maps/basemap", basemap_dir, basemap_dir.is_dir()))

    # 3) 从 v1.0-mini 推断需要的 map location，检查 expansion 里是否有对应 json
    version_dir = dataroot / "v1.0-mini"
    log_json = version_dir / "log.json"
    scene_json = version_dir / "scene.json"
    required_locations = []
    if log_json.is_file():
        try:
            with open(log_json) as f:
                logs = json.load(f)
            if isinstance(logs, dict) and "logs" in logs:
                logs = logs["logs"]
            for log in logs:
                loc = log.get("location")
                if loc and loc not in required_locations:
                    required_locations.append(loc)
        except Exception as e:
            print(f"[WARN] 无法解析 log.json: {e}")
    if not required_locations and scene_json.is_file():
        try:
            with open(scene_json) as f:
                scenes = json.load(f)
            if isinstance(scenes, dict) and "scenes" in scenes:
                scenes = scenes["scenes"]
            for s in scenes:
                log_token = s.get("log_token")
                # 没有 log 无法直接拿 location，用常见 mini 列表兜底
                pass
            if not required_locations:
                required_locations = ["singapore-onenorth", "boston-seaport", "singapore-queensto", "singapore-hollandv"]
        except Exception as e:
            print(f"[WARN] 无法解析 scene.json: {e}")

    if not required_locations:
        required_locations = ["singapore-onenorth", "boston-seaport", "singapore-queensto", "singapore-hollandv"]

    for loc in required_locations:
        exp_json = expansion_dir / f"{loc}.json"
        checks.append(("文件", f"maps/expansion/{loc}.json", exp_json, exp_json.is_file()))

    # 4) 可选：basemap png（convert 里 load_bitmap 会用到）
    for loc in required_locations:
        basemap_png = basemap_dir / f"{loc}.png"
        checks.append(("文件", f"maps/basemap/{loc}.png", basemap_png, basemap_png.is_file()))

    # 打印结果
    for kind, name, path, ok in checks:
        status = "OK" if ok else "MISSING"
        print(f"  [{status}] {kind}: {name}")
        if not ok:
            print(f"        路径: {path}")

    missing = [c for c in checks if not c[3]]
    if missing:
        print()
        print("结论: 存在缺失项，nuscenes2mcap 转换可能报错（如 FileNotFoundError: .../maps/expansion/xxx.json）。")
        print("建议: 从 nuScenes 官网下载 Map Expansion (nuScenes-map-expansion-v1.3.zip)，解压到 数据根目录/maps/ 下。")
        sys.exit(1)
    else:
        print()
        print("结论: 所需目录与文件均存在，可尝试运行 nuscenes2mcap 转换。")
        sys.exit(0)


if __name__ == "__main__":
    main()
