# 输入日志规范（MCAP 主格式）

Phase 0.2 产出。Pipeline 输入以 **MCAP**（nuscenes2mcap 产出）为主，ROS Bag 为可选备用。
以下 MCAP 部分均来自对实际 MCAP 文件（v1.0-mini）的直接扫描，不含猜测性描述。

---

## 一、统一抽象（与格式无关）

- **时间戳**：整条 pipeline 使用**纳秒整数**（`int`，Unix epoch 纳秒）；同一时刻 6 路图像共享**同一时间戳**。
- **相机 ID**：与 topic 前缀一一对应，如 `CAM_FRONT`、`CAM_FRONT_LEFT` 等（nuScenes 6 路）。
- **标定**：每路相机对应独立的 `camera_info` channel，内含完整内参（K/P/R 矩阵）；`get_camera_info(topic_id)` 从此 channel 读取。

---

## 二、MCAP 约定（nuscenes2mcap 实测结果）

> 来源：对 `NuScenes-v1.0-mini-scene-0061.mcap` 运行 `mcap.reader.make_reader` 扫描所得，其余 scene 结构一致。

### 2.1 图像 Channels（Pipeline 主要输入）

| topic | schema | encoding | 内容 | 帧数（scene-0061） |
|-------|--------|----------|------|--------------------|
| `/CAM_FRONT/image_rect_compressed` | `foxglove.CompressedImage` | protobuf | JPEG 压缩图，1600×900 | 224 |
| `/CAM_FRONT_LEFT/image_rect_compressed` | `foxglove.CompressedImage` | protobuf | JPEG 压缩图，1600×900 | 224 |
| `/CAM_FRONT_RIGHT/image_rect_compressed` | `foxglove.CompressedImage` | protobuf | JPEG 压缩图，1600×900 | 217 |
| `/CAM_BACK/image_rect_compressed` | `foxglove.CompressedImage` | protobuf | JPEG 压缩图，1600×900 | 216 |
| `/CAM_BACK_LEFT/image_rect_compressed` | `foxglove.CompressedImage` | protobuf | JPEG 压缩图，1600×900 | 219 |
| `/CAM_BACK_RIGHT/image_rect_compressed` | `foxglove.CompressedImage` | protobuf | JPEG 压缩图，1600×900 | 218 |

**`foxglove.CompressedImage` 关键字段：**

| 字段 | 类型 | 示例值 | 说明 |
|------|------|--------|------|
| `timestamp.seconds` | int64 | `1532402927` | Unix 秒 |
| `timestamp.nanos` | int32 | `612460000` | 纳秒部分 |
| `frame_id` | string | `"CAM_FRONT"` | 等于相机 ID |
| `format` | string | `"jpeg"` | 压缩格式 |
| `data` | bytes | — | JPEG 编码的图像字节 |

**时间戳转纳秒整数**：`timestamp_ns = seconds * 1_000_000_000 + nanos`

---

### 2.2 相机标定 Channels

| topic | schema | encoding |
|-------|--------|----------|
| `/CAM_FRONT/camera_info` | `foxglove.CameraCalibration` | protobuf |
| `/CAM_FRONT_LEFT/camera_info` | `foxglove.CameraCalibration` | protobuf |
| `/CAM_FRONT_RIGHT/camera_info` | `foxglove.CameraCalibration` | protobuf |
| `/CAM_BACK/camera_info` | `foxglove.CameraCalibration` | protobuf |
| `/CAM_BACK_LEFT/camera_info` | `foxglove.CameraCalibration` | protobuf |
| `/CAM_BACK_RIGHT/camera_info` | `foxglove.CameraCalibration` | protobuf |

**`foxglove.CameraCalibration` 关键字段：**

| 字段 | 类型 | 示例值（CAM_FRONT） | 说明 |
|------|------|----------------------|------|
| `timestamp` | Timestamp | 与对应图像帧相同 | 该帧标定时间戳 |
| `frame_id` | string | `"CAM_FRONT"` | 相机 ID |
| `width` | uint32 | `1600` | 图像宽度（像素） |
| `height` | uint32 | `900` | 图像高度（像素） |
| `distortion_model` | string | `""` | nuScenes mini 中为空 |
| `D` | repeated double | `[]` | 畸变系数（nuScenes mini 中为空） |
| `K` | repeated double | 9 个值（3×3 内参矩阵行优先）| fx,0,cx,0,fy,cy,0,0,1 |
| `R` | repeated double | 9 个值（3×3 旋转矩阵行优先）| nuScenes 中为单位阵 |
| `P` | repeated double | 12 个值（3×4 投影矩阵行优先）| 无畸变时 P≈[K\|0] |

**示例 K（CAM_FRONT）：** fx=1266.42, fy=1266.42, cx=816.27, cy=491.51

---

### 2.3 其他 Channels（Pipeline 暂不使用，仅记录）

| topic | schema | 说明 |
|-------|--------|------|
| `/LIDAR_TOP` | `foxglove.PointCloud` | 激光雷达点云 |
| `/RADAR_FRONT` / `..._LEFT` / `..._RIGHT` / `BACK_*` | `foxglove.PointCloud` | 5 路雷达 |
| `/CAM_*/lidar` | `foxglove.ImageAnnotations` | 激光点投影到图像的标注 |
| `/CAM_*/annotations` | `foxglove.ImageAnnotations` | 物体框标注（约 12 Hz 更新） |
| `/tf` | `foxglove.FrameTransform` | 坐标变换树 |
| `/pose` | `foxglove.PoseInFrame` | 自车位姿 |
| `/imu` | `IMU`（jsonschema） | IMU 数据（约 100 Hz） |
| `/odom` | `Pose`（jsonschema） | 里程计 |
| `/gps` | `foxglove.LocationFix` | GPS |
| `/map` / `/semantic_map` / `/drivable_area` | `foxglove.Grid` / `foxglove.SceneUpdate` | 地图数据 |
| `/diagnostics` | `diagnostic_msgs/DiagnosticArray` | 诊断信息（ros1msg 编码） |

---

### 2.4 时间范围（scene-0061 示例）

| 项目 | 值 |
|------|----|
| 起始时间戳（ns） | `1532402927_604844000` |
| 结束时间戳（ns） | `1532402946_797517000` |
| 持续时长 | ≈ 19.2 秒 |
| 图像帧率 | ≈ 12 Hz（各路相机略有差异） |
| 总消息数 | 33 886 条 |

---

## 三、与 ILogReader 的对应

| `ILogReader` 方法 | 实现说明 |
|-------------------|---------|
| `get_topic_names()` | 返回 6 个 `/CAM_*/image_rect_compressed` topic 列表 |
| `get_timeline()` | 扫描上述 6 路图像 channel，按时间戳构建 Timeline（见 `timeline_format.md`） |
| `iter_frames(t_start, t_end, topics)` | 按时间区间流式 yield Frame；解码 `foxglove.CompressedImage` protobuf，时间戳转为纳秒整数 |
| `get_camera_info(topic_id)` | 读取对应 `/CAM_*/camera_info` channel 的第一条消息，解码为 `CameraInfo` 内部结构 |

**读取库**：使用 `mcap` + `mcap-protobuf-support`（`DecoderFactory`）解码 protobuf。`rosbags` 无法读取 nuscenes2mcap 产出的 MCAP（profile 不是 ros2）。

---

## 四、ROS Bag 约定（备用，需 nuscenes2bag）

仅在需要 ROS Bag 输出时使用，主 pipeline 不依赖本节。

- **Topic 命名**：nuscenes2bag 实际输出（常见为 `/nuscenes/camera_front/image_raw` 或类似）。
- **消息类型**：`sensor_msgs/Image` 或 `CompressedImage`；`sensor_msgs/CameraInfo`。
- **时间戳**：`header.stamp`；同帧 6 路共享相同 stamp。
- **读取库**：`rosbags`（无需本机安装 ROS）。
