import time
import unittest

from teleop_messages import (
    TRACK_MAGIC,
    Envelope,
    LatestFrameAssembler,
    PreviewFrameHeader,
    empty_controller,
    session_packet,
    tracking_packet,
)


class ProtocolTests(unittest.TestCase):
    def test_preview_header_roundtrip(self):
        hdr = PreviewFrameHeader(
            frame_id=42,
            capture_ts_ns=123456789,
            width=2560,
            height=720,
            eye_mode=0,
            payload_packets=8,
        )
        parsed = PreviewFrameHeader.unpack(hdr.pack())
        self.assertEqual(parsed.frame_id, 42)
        self.assertEqual(parsed.width, 2560)
        self.assertTrue(parsed.is_idr)

    def test_tracking_packet_json(self):
        raw = tracking_packet(
            seq=7,
            send_ts_ns=99,
            session="abc",
            head_pose=[0, 1.6, 0, 0, 0, 0, 1],
            controller=empty_controller(),
        )
        env = Envelope.unpack(raw)
        self.assertEqual(env.magic, TRACK_MAGIC)
        self.assertEqual(env.payload["session"], "abc")
        self.assertEqual(len(env.payload["head"]["pose"]), 7)

    def test_session_hello(self):
        raw = session_packet(1, time.time_ns(), "hello", device="quest3", app="1.0.0")
        env = Envelope.unpack(raw)
        self.assertEqual(env.payload["type"], "hello")
        self.assertEqual(env.payload["device"], "quest3")

    def test_latest_frame_drops_stale(self):
        asm = LatestFrameAssembler()
        h1 = PreviewFrameHeader(1, 10, 16, 16)
        self.assertIsNone(asm.push(1, b"A", start=True, end=False, header=h1))
        h2 = PreviewFrameHeader(2, 20, 16, 16)
        done = asm.push(2, b"B", start=True, end=True, header=h2)
        self.assertIsNotNone(done)
        self.assertEqual(done[0].frame_id, 2)
        self.assertEqual(done[1], b"B")
        self.assertIsNone(asm.push(1, b"old", start=True, end=True, header=h1))


if __name__ == "__main__":
    unittest.main()
