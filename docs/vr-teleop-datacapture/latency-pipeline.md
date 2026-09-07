# 低延时视频管线实施细则

配合主方案第 4 节。这里给出可直接拿去联调的编码、发送、解码参数。目标：**相机出帧到头盔 Surface 呈现 P50 ≤ 50 ms**。

## 1. 推荐拓扑

```
[全局快门双目] --CSI/GMSL/USB3--> [Orin / x86+NVENC]
        |  NvBuf / DMA-BUF / CUDA
        +--> preview encoder (H.264 GOP=1, CBR 30 Mbps)
        |         \--> UDP RTP :50020  ==>  AP  ==>  Headset MediaCodec
        +--> record encoder  (HEVC GOP=30 或 JPEG 落盘)
                  \--> MCAP on NVMe
```

预览进程与录像进程只共享只读帧环，禁止互相阻塞。

## 2. 采集

### 2.1 V4L2（工业相机 / UVC）

- 像素：`NV12` 或 `YUYV`（后者进 GPU 立刻转 NV12）。
- 缓冲：`V4L2_MEMORY_DMABUF`，深度 3。深度 8+ 等于主动加延时。
- 触发：左右目 `external trigger`，源 60/90 Hz。
- 用户态：`epoll` 等 `DQBUF`，拿到 fd 立刻 `NvBufSurface` import，**不要** `read()` 到堆内存。

### 2.2 ZED Mini / ZED X

用 SDK grab 拿 GPU 指针（`sl::VIEW::LEFT/RIGHT` + `sl::MEM::GPU`），自行送 NVENC。不要用 ZED Streaming 模块当头盔预览（接收端被 SDK 绑死，且不走 MediaCodec Surface 路径）。

### 2.3 预处理（合计 < 3 ms）

在 CUDA 一发 kernel 内完成：

1. 左右去畸变（预计算 map，`cudaTexture`）。
2. 可选 2×2 降尺度到预览分辨率。
3. 并排拼成 `2560×720 NV12`，或保持两路独立。
4. 在图像左上 8×2 像素写入时间码（可选，便于 LED 法对照）。

## 3. 预览编码

### 3.1 x86 + NVIDIA NVENC（FFmpeg）

```bash
# 输入是 NV12 CUDA 帧时，用 ffmpeg CUDA 上传或自写 NvEnc API。
# 下面是等价的 ull 预设，联调可用 videotestsrc 代替相机。
ffmpeg -hwaccel cuda -hwaccel_output_format cuda \
  -f rawvideo -pix_fmt nv12 -s 2560x720 -r 60 -i - \
  -c:v h264_nvenc -preset p1 -tune ull \
  -rc cbr -b:v 30M -maxrate 30M -bufsize 500k \
  -g 1 -bf 0 -profile:v high \
  -forced-idr 1 -strict_gop 1 \
  -delay 0 -zerolatency 1 \
  -f rtp rtp://192.168.10.20:50020
```

`bufsize` 必须远小于「一帧码率×数帧」，否则 CBR 会攒缓冲。30 Mbps @ 60 fps ≈ 62.5 kB/帧，`bufsize=500k` 约 8 帧上限，仍偏大；联调可试 `250k`。

### 3.2 Jetson `nvv4l2h264enc`

见 `reference/pipeline/gst_robot_tx.sh`。关键属性：

| 属性 | 值 |
| --- | --- |
| `iframeinterval` | 1 |
| `insert-sps-pps` | true |
| `maxperf-enable` | true |
| `bitrate` | 30000000 |
| `control-rate` | constant_bitrate |
| `profile` | High |
| `num-B-Frames` | 0 |
| `idrinterval` | 1 |
| `preset-level` | UltraFastPreset / LowLatency |

### 3.3 自写 NvEnc（量产建议）

GStreamer 仍有队列元件容易被误加成 2–3 帧。量产用 NvEnc API：

1. `NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY`
2. `enableIntraRefresh=0`，`gopLength=1`
3. `enableLookahead=0`，`enableBFrames=0`
4. 输入资源：`CUdeviceptr` 或 `CUarray`，注册为 encode resource
5. 输出回调里立刻 RTP 分包，不等下一帧

伪代码流程：

```
on_frame(dmabuf):
    if encoder.busy:
        drop_this_or_drop_in_flight()   # 保最新
        return
    nvenc.encode(dmabuf, capture_ts)
on_encoded(nalus, capture_ts, frame_id):
    rtp.send(nalus, header{capture_ts, frame_id, eye=SBS})
```

## 4. RTP / 组包

- 时钟 90 kHz。
- 一帧多个 NALU：每个 NALU 按 RFC 6184 分片，`FU-A`。
- 自定义 20 字节扩展头（见 protocol.md）放在每帧首包：`capture_ts_ns`、`frame_id`、`eye_mode`、`width/height`。
- 发送套接字：`SO_PRIORITY`、`UDP_CORK` 仅在一帧内开启，帧结束立刻 `uncork`。
- 不设 `SO_SNDBUF` 过大（例如 > 4 MB），避免内核堆旧帧。

接收端（头盔插件）：

```
pkt = recv()
if pkt.frame_id < current: drop
if pkt.frame_id > current: discard_incomplete(); start_new()
append(); if marker: submit_to_mediacodec()
```

队列：`inflight_decode <= 1`。解码器未取走时，新的完整帧覆盖待送帧。

## 5. 头盔 MediaCodec

Java / NDK 等价配置：

```
MediaFormat fmt = MediaFormat.createVideoFormat(MIMETYPE_VIDEO_AVC, 2560, 720);
fmt.setInteger(MediaFormat.KEY_LOW_LATENCY, 1);
fmt.setInteger(MediaFormat.KEY_PRIORITY, 0);          // realtime
fmt.setInteger("vendor.qti-ext-dec-picture-order.enable", 1); // 若存在
codec.configure(fmt, surfaceFromOpenXR, null, 0);
codec.setParameters({ PARAMETER_KEY_LOW_LATENCY: 1 });
codec.start();
```

SPS/PPS：因 GOP=1，每帧都可能带；解码器需允许中途刷新。发送端 `insert-sps-pps=1`。

Surface 来源：

1. Unity：原生插件创建 `SurfaceTexture`，转 `Android Surface` 给 codec，纹理 ID 交给 OpenXR `XrSwapchain` 或 Unity 外部纹理。
2. 更低延时：用 OpenXR `XR_KHR_android_surface_swapchain`（若运行时支持），解码直接画到合成层，App 不再 blit。

Quest 与 Pico 均为 Android，这条路径共用。厂商 SDK 不必介入解码。

## 6. 联调阶梯

按顺序替换输入，每步都用 LED 或 `gst-launch` 计时：

| 步 | 命令意图 | 通过标准 |
| --- | --- | --- |
| 1 | `videotestsrc` → NVENC → 本机 `fakesink` | 编码 < 8 ms |
| 2 | 同上 → UDP → 同机 `rtph264depay ! nvv4l2decoder` | 往返 < 20 ms |
| 3 | UDP → 头盔 MediaCodec → 全屏四边形 | MTP < 60 ms（测试图） |
| 4 | 换真实相机 | MTP P50 < 50 ms，P95 < 80 ms |
| 5 | 加上行追踪，确认视频不受影响 | 预览延时变化 < 3 ms |

## 7. 常见超预算对照

| 测到的段 | 通常原因 | 处理 |
| --- | --- | --- |
| 采集 > 20 ms | 卷帘 / 自动曝光 / 缓冲 8 格 | 全局快门、锁曝光、3 格缓冲 |
| 编码 > 12 ms | B 帧、lookahead、分辨率 4K | GOP=1、720p、ull |
| 空口 > 15 ms | 双无线、1 Mbps 重编、办公 AP | 有线进 AP、25 Mbps+、独占信道 |
| 解码 > 15 ms | ByteBuffer、未开 LOW_LATENCY | Surface + KEY_LOW_LATENCY |
| 上屏 > 25 ms | Unity 渲染后再 Blit、60 Hz 应用 | Quad Layer、90 Hz |
