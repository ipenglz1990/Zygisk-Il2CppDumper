#!/usr/bin/env bash
# Linux decode sink for measuring encode+network+decode without a headset.
# On-device path must use Android MediaCodec + Surface instead of this script.
set -euo pipefail

PORT="${1:-50020}"

gst-launch-1.0 -e \
  udpsrc port="${PORT}" buffer-size=65536 \
    ! "application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" \
    ! rtpjitterbuffer latency=0 drop-on-latency=true \
    ! rtph264depay \
    ! h264parse \
    ! avdec_h264 \
    ! videoconvert \
    ! fpsdisplaysink text-overlay=true sync=false
