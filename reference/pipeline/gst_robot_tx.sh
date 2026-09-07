#!/usr/bin/env bash
# Robot-side preview sender reference (Jetson).
# Replace nvarguscamerasrc / v4l2src with the real stereo source.
# Headset IP is the only required argument.
set -euo pipefail

HEADSET_IP="${1:?usage: gst_robot_tx.sh <headset_ip>}"
PORT="${2:-50020}"
BITRATE="${BITRATE:-30000000}"
WIDTH="${WIDTH:-2560}"
HEIGHT="${HEIGHT:-720}"
FPS="${FPS:-60}"

# videotestsrc is for bring-up. Swap in:
#   nvarguscamerasrc ! nvvideoconvert ! ...
# or a CUDA appsrc feeding SBS NV12.
gst-launch-1.0 -e \
  videotestsrc is-live=true pattern=ball \
    ! "video/x-raw,width=${WIDTH},height=${HEIGHT},framerate=${FPS}/1,format=NV12" \
    ! nvvidconv \
    ! "video/x-raw(memory:NVMM),format=NV12" \
    ! nvv4l2h264enc \
        bitrate="${BITRATE}" \
        control-rate=1 \
        iframeinterval=1 \
        idrinterval=1 \
        insert-sps-pps=true \
        maxperf-enable=true \
        num-B-Frames=0 \
        preset-level=1 \
        profile=4 \
    ! h264parse config-interval=-1 \
    ! rtph264pay pt=96 mtu=1200 config-interval=1 \
    ! udpsink host="${HEADSET_IP}" port="${PORT}" sync=false async=false
