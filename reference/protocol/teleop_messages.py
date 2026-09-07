"""Wire helpers for Quest/Pico robot teleop.

Preview uses RTP plus a 24-byte extra header on the first packet of each frame.
Tracking/session use a 16-byte prefix plus UTF-8 JSON (XRoboToolkit-compatible).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Literal

VIDEO_MAGIC = 0x56525031  # VRP1
TRACK_MAGIC = 0x58525431  # XRT1
PREFIX = struct.Struct("<IIQ")  # magic, seq, send_ts_ns
VIDEO_HDR = struct.Struct("<IIQHHBBH")

EyeMode = Literal[0, 1, 2]  # sbs, left, right


@dataclass
class PreviewFrameHeader:
    frame_id: int
    capture_ts_ns: int
    width: int
    height: int
    eye_mode: EyeMode = 0
    is_idr: bool = True
    has_sps_pps: bool = True
    payload_packets: int = 0

    def pack(self) -> bytes:
        flags = (1 if self.is_idr else 0) | (2 if self.has_sps_pps else 0)
        return VIDEO_HDR.pack(
            VIDEO_MAGIC,
            self.frame_id & 0xFFFFFFFF,
            self.capture_ts_ns & 0xFFFFFFFFFFFFFFFF,
            self.width,
            self.height,
            self.eye_mode,
            flags,
            self.payload_packets,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "PreviewFrameHeader":
        magic, frame_id, ts, w, h, eye, flags, pkts = VIDEO_HDR.unpack(data[: VIDEO_HDR.size])
        if magic != VIDEO_MAGIC:
            raise ValueError(f"bad video magic: {magic:#x}")
        return cls(
            frame_id=frame_id,
            capture_ts_ns=ts,
            width=w,
            height=h,
            eye_mode=eye,  # type: ignore[arg-type]
            is_idr=bool(flags & 1),
            has_sps_pps=bool(flags & 2),
            payload_packets=pkts,
        )


@dataclass
class Envelope:
    magic: int
    seq: int
    send_ts_ns: int
    payload: dict[str, Any]

    def pack(self) -> bytes:
        body = json.dumps(self.payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return PREFIX.pack(self.magic, self.seq & 0xFFFFFFFF, self.send_ts_ns) + body

    @classmethod
    def unpack(cls, data: bytes) -> "Envelope":
        magic, seq, ts = PREFIX.unpack(data[: PREFIX.size])
        payload = json.loads(data[PREFIX.size :].decode("utf-8"))
        return cls(magic=magic, seq=seq, send_ts_ns=ts, payload=payload)


def tracking_packet(
    seq: int,
    send_ts_ns: int,
    *,
    session: str,
    head_pose: list[float],
    hand_mode: int = 1,
    controller: dict[str, Any] | None = None,
    hand: dict[str, Any] | None = None,
    body_joints: list[list[float]] | None = None,
    trackers: list[dict[str, Any]] | None = None,
) -> bytes:
    payload: dict[str, Any] = {
        "session": session,
        "head": {"pose": head_pose, "status": 1, "handMode": hand_mode},
    }
    if controller is not None:
        payload["controller"] = controller
    if hand is not None:
        payload["hand"] = hand
    if body_joints:
        payload["body"] = {"joints": body_joints}
    if trackers:
        payload["trackers"] = trackers
    return Envelope(TRACK_MAGIC, seq, send_ts_ns, payload).pack()


def session_packet(seq: int, send_ts_ns: int, msg_type: str, **fields: Any) -> bytes:
    payload = {"type": msg_type, **fields}
    return Envelope(TRACK_MAGIC, seq, send_ts_ns, payload).pack()


def empty_controller() -> dict[str, Any]:
    one = {
        "pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "axisX": 0.0,
        "axisY": 0.0,
        "axisClick": 0,
        "grip": 0.0,
        "trigger": 0.0,
        "primaryButton": 0,
        "secondaryButton": 0,
        "menuButton": 0,
    }
    return {"left": dict(one), "right": dict(one)}


@dataclass
class LatestFrameAssembler:
    """Drop incomplete frames as soon as a newer frame_id arrives."""

    current_id: int | None = None
    parts: list[bytes] = field(default_factory=list)
    header: PreviewFrameHeader | None = None

    def push(self, frame_id: int, chunk: bytes, *, start: bool, end: bool, header: PreviewFrameHeader | None):
        if self.current_id is not None and frame_id < self.current_id:
            return None
        if self.current_id is None or frame_id > self.current_id:
            self.current_id = frame_id
            self.parts = []
            self.header = header
        if start and header is not None:
            self.header = header
        self.parts.append(chunk)
        if end:
            blob = b"".join(self.parts)
            hdr = self.header
            self.parts = []
            return hdr, blob
        return None
