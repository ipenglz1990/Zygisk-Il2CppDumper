# 参考实现碎片

这些文件配合 `docs/vr-teleop-datacapture/` 使用，不是完整机器人栈，只覆盖协议、编码预设和联调命令。

```
configs/          延时预算与 NVENC / MediaCodec 参数
protocol/         Python 组包、最新帧聚合、单测
pipeline/         Jetson 发送、Linux 接收、MTP 测量步骤
```

```bash
python3 protocol/test_teleop_messages.py
# Jetson 上：
./pipeline/gst_robot_tx.sh 192.168.10.20
```
