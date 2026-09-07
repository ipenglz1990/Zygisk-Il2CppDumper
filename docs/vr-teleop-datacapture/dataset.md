# 数据采集格式

原始会话写 **MCAP**。训练再导出 **LeRobot v2** 与可选 **HDF5**。时间轴以机器人 `CLOCK_MONOTONIC` 为主，XR 经 `clock_sync` 对齐。

## 1. 会话元数据 `session.json`

```json
{
  "schema": "vr-teleop-session/v1",
  "session_id": "8f2a9c",
  "task": "把杯子放到托盘右侧",
  "scene_id": "kitchen_a",
  "operator": "op_07",
  "headset": { "model": "pico4u", "sn": "", "app": "1.0.0" },
  "robot": { "type": "dual_arx_r5", "id": "cell-2" },
  "cameras": {
    "head_left":  { "w": 1280, "h": 720, "fps": 60, "shutter": "global" },
    "head_right": { "w": 1280, "h": 720, "fps": 60, "shutter": "global" },
    "wrist_left": { "w": 640, "h": 480, "fps": 30, "shutter": "rolling" },
    "wrist_right":{ "w": 640, "h": 480, "fps": 30, "shutter": "rolling" }
  },
  "preview": { "codec": "h264", "bitrate_mbps": 30, "gop": 1 },
  "qa": { "status": "pass", "mtp_p50_ms": 47.2, "drop_pct": 0.2 },
  "episode_outcome": "success"
}
```

## 2. MCAP Topics

| Topic | 频率 | 载荷 |
| --- | --- | --- |
| `/cam/head/left/image` | 30–60 | JPEG 或 H.264 访问单元 + `capture_ts_ns` |
| `/cam/head/right/image` | 30–60 | 同上 |
| `/cam/wrist/left/image` | 30 | JPEG |
| `/cam/wrist/right/image` | 30 | JPEG |
| `/cam/head/camera_info` | 1 | K, D, R, P, 基线 |
| `/robot/joint_state` | 100–200 | q, dq, τ |
| `/robot/ee_pose` | 100 | 左右末端 w.r.t base |
| `/robot/command` | 200 | 下发 q_des 或 ee 增量 |
| `/xr/state` | 90 | 与协议 JSON 相同 |
| `/xr/clock_offset` | 2 | `offset_ns`, `rtt_ns` |
| `/event/record` | 事件 | start/stop/mark |
| `/diag/preview_latency` | 2 | 头盔回传的 decode 样本 |

图像与状态 **不要** 强行重采样到同一 fps 再写入 MCAP。保持各自原频率，导出训练时再对齐。

## 3. 导出 LeRobot v2

对齐到 **30 fps**（或头视 60 的整数下采样）：

- `observation.state`：关节位置（及夹爪）。
- `observation.images.head_left` / `head_right` / `wrist_left` / `wrist_right`：mp4。
- `action`：该帧对应的下发指令（与采集时 `command` 对齐，**不要**用 `q[t+1]-q[t]` 冒充，除非确认是位置伺服且文档声明）。
- `observation.xr_head`、`observation.xr_ctrl_left`、`observation.xr_ctrl_right`：可选，7 维。
- `timestamp`、`episode_index`、`task`。

混训 Quest / Pico 时：只把 OpenXR 公共字段放进 `observation.*`；Pico `body` / `trackers` 放 `observation.pico_body` 可选特征，Quest 填 NaN 并在 `meta/info.json` 标明。

## 4. 导出 HDF5（单集）

```
episode_000.hdf5
  observations/
    qpos                 (T, nq)
    qvel                 (T, nq)
    ee_pose              (T, 2, 7)
    images/
      head_left          (T, H, W, 3) uint8 或 JPEG 字节
      head_right
      wrist_left
      wrist_right
    xr/
      head               (T, 7)
      left_controller    (T, 7)
      right_controller   (T, 7)
      left_hand          (T, 26, 7)
      right_hand         (T, 26, 7)
  action                 (T, na)
  timestamps_ns          (T,)
  attrs.task             str
  attrs.outcome          success|fail|abort
```

`T` 以头视左目为轴，其他流 binary search 最近邻，阈值 8 ms，超阈标记该帧 `valid=0`。

## 5. 质检门槛（自动）

写入 `session.json qa`：

- 预览丢包 > 1% 或 MTP 探针 P95 > 90 ms → `reject_preview`（仍可留作离线，不进默认训练集）。
- 左右目时间差 > 2 ms 超过 5% 帧 → `reject_sync`。
- 急停触发 → `abort`。
- 关节超限 / IK 失败占比 > 3% → `reject_control`。
- 操作员标记 fail → `fail`。

只有 `qa.status=pass` 且 `episode_outcome=success` 进入默认 LeRobot 导出。
