# 线协议：预览、追踪、会话

所有多字节整数 **little-endian**。默认同网 IPv4。头盔为客户端，机器人（或车载工控机）为服务端。

## 1. 端口

| 端口 | 方向 | 内容 |
| --- | --- | --- |
| UDP 50020 | 机器人 → 头盔 | 预览 RTP（H.264） |
| UDP 50021 | 头盔 → 机器人 | 追踪状态 90 Hz |
| UDP 50022 | 双向 | 会话、心跳、采集事件、时钟同步 |
| TCP 50023 | 督导机 ↔ 机器人 | 任务元数据、QA、标定下载（非热路径） |

发现：头盔启动后向机器人 `50022` 发 `hello`，机器人回 `hello_ack`（含视频 SSRCs、推荐码率、会话 id）。之后 20 Hz 心跳。超时见主方案安全节。

## 2. 预览帧扩展头

插在每帧 **首个 RTP 包** 的 header extension（one-byte header, id=1）：

| 偏移 | 类型 | 含义 |
| --- | --- | --- |
| 0 | u32 | `magic = 0x56525031` ("VRP1") |
| 4 | u32 | `frame_id` 单调 +1 |
| 8 | u64 | `capture_ts_ns` 机器人 CLOCK_MONOTONIC |
| 16 | u16 | `width` |
| 18 | u16 | `height` |
| 20 | u8 | `eye_mode` 0=SBS 左右并排, 1=左, 2=右 |
| 21 | u8 | `flags` bit0=IDR, bit1=有 SPS/PPS |
| 22 | u16 | `payload_packets` 本帧 RTP 包数（估计，0=未知） |

`marker` bit 表示帧结束。接收端以 `frame_id` 聚合。

## 3. 追踪包（50021）

为便于与 XRoboToolkit 互操作，**载荷为单行 JSON**（无 BOM），外裹 16 字节前缀：

```
u32 magic = 0x58525431   # "XRT1"
u32 seq
u64 send_ts_ns           # 头盔 CLOCK_MONOTONIC
utf8 json
```

JSON 每 90 Hz 一发，缺测字段省略或 `null`。公共字段：

```json
{
  "session": "8f2a...",
  "head": { "pose": [0, 1.6, 0, 0, 0, 0, 1], "status": 1, "handMode": 1 },
  "controller": {
    "left": {
      "pose": [0, 0, 0, 0, 0, 0, 1],
      "axisX": 0.0, "axisY": 0.0, "axisClick": 0,
      "grip": 0.0, "trigger": 0.0,
      "primaryButton": 0, "secondaryButton": 0, "menuButton": 0
    },
    "right": { }
  },
  "hand": {
    "left":  { "isActive": 1, "scale": 1.0, "joints": [ /* 26 x 7 */ ] },
    "right": { "isActive": 1, "scale": 1.0, "joints": [] }
  },
  "body": { "joints": [] },
  "trackers": [ { "sn": "XXXX", "p": [0,0,0,0,0,0,1], "va": [0,0,0,0,0,0] } ]
}
```

约定：

- `pose` = `[x,y,z,qx,qy,qz,qw]`，OpenXR 右手系，单位米。
- `handMode`：0 无，1 手柄，2 手追。
- `body.joints`：Pico 24 关节；Quest 省略。
- `joints` 每个 7 个数；手 26 个，顺序遵循 OpenXR `XR_HAND_JOINT_*`。
- 按钮：0/1；`grip`/`trigger`：0.0–1.0。

量产若 JSON 解析占头盔或机器人过多 CPU，可切换为同字段 FlatBuffers，魔数改为 `XRT2`。先 JSON 联调。

## 4. 会话包（50022）

同样 16 字节前缀 + JSON。`type` 枚举：

| type | 方向 | 作用 |
| --- | --- | --- |
| `hello` | XR→R | `{device:"quest3"|"pico4u", app:"1.0.0", ip}` |
| `hello_ack` | R→XR | `{session, video_port, bitrate_mbps, stereo:"sbs"}` |
| `heartbeat` | 双向 | `{seq, send_ts_ns, last_rtt_ns}` |
| `clock_sync` | 双向 | 类 NTP：T1/T2/T3/T4，估计偏移 |
| `record_start` / `record_stop` | XR→R | `{task_id, episode_id}` |
| `record_mark` | XR→R | `{label:"fail"|"good"|" interven"}` |
| `estop` | 任一 | `{source:"headset"|"supervisor"|"watchdog"}` |
| `hold` | R→XR | 进入 HOLD，头盔可显示红框 |
| `latency_sample` | XR→R | `{frame_id, capture_ts_ns, decode_ts_ns}` 2 Hz |

`clock_sync` 至少启动时 20 次，之后每秒 2 次。机器人保存 `offset_ns = ((T2-T1)+(T3-T4))/2` 的滑动中位数。

## 5. 丢包与拥塞

- 视频：**不重传**。连续 15 帧不完整 → 会话包通知机器人降一档（1080→720 或 90→60 fps）。
- 追踪：丢失单包可插值；**连续 5 包（≈55 ms）丢失 → HOLD**。
- 心跳：双向 20 Hz；对端 150 ms 无心跳 → HOLD。

## 6. 安全备注

协议无加密时仅用于隔离实验网。产线 VLAN 应加预共享密钥（AEAD 包头 16 字节 nonce+tag），或走 WireGuard。密钥不进本仓库。
