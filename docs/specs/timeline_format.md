# Timeline 序列化格式

Phase 0.3 产出：`ILogReader.get_timeline()` 的返回结构及其持久化格式，用于断点续传与输出严格时间戳对齐。

---

## 一、设计目标

1. **贯穿整个 pipeline**：从输入 MCAP 解析出的 Timeline，经 Stage 1→5 全程传递，输出 MCAP 写入时严格按 Timeline 中的时间戳写入，保证 6 路同步。
2. **可持久化**：序列化为 JSON 文件落盘，供断点续传（ICheckpointManager）读取。
3. **内存友好**：Timeline 本体只存元数据（时间戳 + 偏移索引），不缓存图像字节；`iter_frames` 按需从原始 MCAP seek 读取。
4. **格式无关**：Timeline 内部只用纳秒整数时间戳，不依赖 MCAP/Bag 具体字段名。

---

## 二、内存中的数据结构

```python
# 见 src/ad_3dgs/types/__init__.py 中的完整定义

@dataclass
class FrameRef:
    """单路相机单帧的元数据引用（不含图像字节）。"""
    topic: str           # 如 "/CAM_FRONT/image_rect_compressed"
    timestamp_ns: int    # 纳秒整数 Unix 时间戳
    log_offset: int      # 在 MCAP 文件中的字节偏移（用于 seek 读取）
    data_length: int     # 消息字节长度（可选，用于预分配缓冲）

@dataclass
class TimelineEntry:
    """一个同步时刻：所有可用相机在该时刻的帧引用。"""
    timestamp_ns: int                        # 该时刻的代表时间戳（纳秒）
    frames: dict[str, FrameRef]              # topic -> FrameRef；6 路相机不一定全有

@dataclass
class Timeline:
    """整段 Log 的时间戳序列，可按区间切片供各 Stage 使用。"""
    source_path: str                         # 原始 MCAP 文件绝对路径
    camera_topics: list[str]                 # 6 路图像 topic 列表，有序
    entries: list[TimelineEntry]             # 按 timestamp_ns 升序排列
    start_ns: int                            # entries[0].timestamp_ns
    end_ns: int                              # entries[-1].timestamp_ns
```

---

## 三、同步策略

nuscenes2mcap 产出的 MCAP 中，6 路相机帧**并非精确同一纳秒**，但 nuScenes 元数据中同一「sample」下各相机共享同一 sample_token，时间戳差距通常 < 1 ms。

**构建 TimelineEntry 的规则：**

1. 以 `/CAM_FRONT/image_rect_compressed` 的时间戳为锚点（该路帧率最稳定）。
2. 对每个锚点时间戳 `t`，将时间窗口 `[t - 50ms, t + 50ms]` 内其余 5 路相机的最近帧归入同一 `TimelineEntry`。
3. 若某路相机在该窗口内无帧，`frames` 中对应 topic 缺失（下游须处理缺帧情况）。
4. 窗口大小 `sync_window_ms` 在 `config/pipeline.yaml` 中可配置，默认 50 ms。

---

## 四、持久化格式（JSON）

落盘路径：`data/intermediate/stage1_timeline/<scene_id>_timeline.json`

```json
{
  "version": 1,
  "source_path": "/home/luosx/3dgs/data/input/NuScenes-v1.0-mini-scene-0061.mcap",
  "camera_topics": [
    "/CAM_FRONT/image_rect_compressed",
    "/CAM_FRONT_LEFT/image_rect_compressed",
    "/CAM_FRONT_RIGHT/image_rect_compressed",
    "/CAM_BACK/image_rect_compressed",
    "/CAM_BACK_LEFT/image_rect_compressed",
    "/CAM_BACK_RIGHT/image_rect_compressed"
  ],
  "start_ns": 1532402927604844000,
  "end_ns":   1532402946797517000,
  "entries": [
    {
      "timestamp_ns": 1532402927604844000,
      "frames": {
        "/CAM_FRONT/image_rect_compressed": {
          "topic": "/CAM_FRONT/image_rect_compressed",
          "timestamp_ns": 1532402927612460000,
          "log_offset": 1048576,
          "data_length": 131197
        },
        "/CAM_FRONT_LEFT/image_rect_compressed": {
          "topic": "/CAM_FRONT_LEFT/image_rect_compressed",
          "timestamp_ns": 1532402927612460000,
          "log_offset": 1181773,
          "data_length": 128400
        }
      }
    }
  ]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | int | 格式版本号，当前为 1；读取时检查兼容性 |
| `source_path` | string | 原始 MCAP 绝对路径；恢复时校验文件存在 |
| `camera_topics` | string[] | 6 路 topic 有序列表 |
| `start_ns` / `end_ns` | int | 全序列时间范围，纳秒 |
| `entries[].timestamp_ns` | int | 该同步时刻的代表时间戳（锚点，纳秒） |
| `entries[].frames` | object | key 为 topic，value 为 FrameRef |
| `FrameRef.log_offset` | int | MCAP 文件中消息体的字节偏移（由 `mcap` reader 的 `message.data_start_offset` 提供） |
| `FrameRef.data_length` | int | 消息体字节长度 |

---

## 五、使用约定

- **Stage 1（LogReader）**：调用 `get_timeline()` 构建并返回 `Timeline`，同时序列化为 JSON 落盘（幂等，相同 MCAP 产出相同 JSON）。
- **Stage 2–4（重建/渲染/合成）**：通过 `Timeline.entries` 切片获取帧列表，不直接访问 MCAP。
- **Stage 5（LogWriter）**：遍历 `Timeline.entries`，严格按 `entry.timestamp_ns` 写入输出 MCAP，保证 6 路同步。
- **断点恢复**：`ICheckpointManager` 存储 `timeline_path`（JSON 路径）；恢复时直接从 JSON 反序列化，无需重新扫描 MCAP。
- **内存上限**：`Timeline` 对象本身（全量 entries，约 200 帧 × 6 路 × 每条 ~100 B）≈ 120 KB，可常驻内存；图像字节按需从 MCAP seek 读取。
