# Photon-to-photon 测量步骤

## LED 金标准（验收、对外数字）

1. 使用 100 Hz 或 1000 Hz 递进时间码 LED 板，放在机器人头视正前方。
2. 头盔戴在固定支架上，镜片朝外，让外录 3D 相机同时拍到：
   - 真实 LED 板
   - 头盔镜片里显示的 LED 板
3. 外录用 ≥120 fps。逐帧读两个时间码，差值即 MTP。
4. 每个配置至少 30 个样本，记录 P50 / P95 / std。
5. 对照表至少包含：
   - videotestsrc 有线环回（编码+解码下限）
   - 真相机 + 独占 Wi-Fi 6
   - Quest 3 与 Pico 4 Ultra 各一次（同码率、同分辨率）

不要用手机慢动作拍镜片估延时（快门卷帘和不同步会偏 10–30 ms）。

## 工程探针（每次采集）

1. 预览扩展头带 `capture_ts_ns` 与 `frame_id`。
2. 头盔 `MediaCodec.BufferInfo.presentationTimeUs` 到达且 `releaseOutputBuffer(..., true)` 后记 `decode_ts_ns`。
3. 2 Hz 经 50022 回传 `latency_sample`。
4. 机器人：`mtp_est_ms = (decode_ts_ns - capture_ts_ns + clock_offset_ns) / 1e6 + 1000 / refresh_hz / 2`。
5. 与 LED 法做一次线性标定，把常数偏置写进 `session.json`。

## 分段插桩

| 戳 | 位置 |
| --- | --- |
| T0 | 相机 SOF / 触发沿 |
| T1 | DQBUF / SDK grab |
| T2 | NVENC 输出回调 |
| T3 | 首包 `sendto` |
| T4 | 头盔收齐一帧 |
| T5 | `queueInputBuffer` |
| T6 | `releaseOutputBuffer` |
| T7 | OpenXR `endFrame` |

哪一段超 `latency_budget.yaml` 就只改那一段。
