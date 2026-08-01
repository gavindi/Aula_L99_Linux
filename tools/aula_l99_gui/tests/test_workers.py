"""KeyboardWorker path tests: the 2.4G dongle interrupt-report path (new) and
the cable feature-report path (regression guard for the refactor). The worker
opens HidrawTransport itself, so the real transport is patched out for a fake
that just records what it wrote and hands back queued replies."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

from aula_l99_gui import workers
from aula_l99_hacky import protocol as kb_protocol


class FakeHidraw:
    def __init__(self, read_replies=None, feature_replies=None):
        self._read_replies = list(read_replies or [])
        self._feature_replies = list(feature_replies or [])
        self.written = []
        self.feature_payloads = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, payload: bytes) -> None:
        self.written.append(bytes(payload))

    def read_report(self, max_length: int = 64) -> bytes:
        if not self._read_replies:
            raise AssertionError("unexpected read_report call")
        return self._read_replies.pop(0)

    def set_feature(self, payload: bytes) -> None:
        self.feature_payloads.append(bytes(payload))

    def get_feature(self, report_id: int, size: int) -> bytes:
        if not self._feature_replies:
            raise AssertionError("unexpected get_feature call")
        return self._feature_replies.pop(0)


def _run(worker: workers.KeyboardWorker) -> dict:
    results = {}
    worker.finished.connect(lambda ok, msg: results.setdefault("finished", (ok, msg)))
    worker.run()
    return results


def _version_variant(reply: bytes, version: int) -> bytes:
    variant = bytearray(reply)
    variant[kb_protocol.SESSION_INIT_VERSION_BYTE] = version
    variant[-1] = kb_protocol.checksum(variant[:-1])
    return bytes(variant)


def _cable_ack(opcode: int) -> bytes:
    reply = bytearray(kb_protocol.PACKET_SIZE)
    reply[0] = kb_protocol.CMD_PREFIX
    reply[1] = opcode
    reply[kb_protocol.ACK_OFFSET] |= kb_protocol.ACK_FLAG
    return bytes([kb_protocol.REPORT_ID]) + bytes(reply)


def test_keyboard_worker_dongle_handshake_acks():
    fake = FakeHidraw(read_replies=[
        kb_protocol.SESSION_INIT_IN, kb_protocol.SESSION_QUERY_IN])
    worker = workers.KeyboardWorker(
        "/dev/hidraw7", kb_protocol.build_dongle_handshake(), dongle=True)
    with patch.object(workers, "HidrawTransport", lambda *a, **k: fake):
        results = _run(worker)

    assert results["finished"] == (True, "ok")
    assert fake.written == [
        bytes([kb_protocol.REPORT_ID]) + kb_protocol.SESSION_INIT_OUT,
        bytes([kb_protocol.REPORT_ID]) + kb_protocol.SESSION_QUERY_OUT,
    ]
    for payload in fake.written:
        assert len(payload) == kb_protocol.DONGLE_PACKET_SIZE + 1


def test_keyboard_worker_dongle_accepts_other_version_byte():
    variant = _version_variant(kb_protocol.SESSION_INIT_IN, 0x08)
    fake = FakeHidraw(read_replies=[variant, kb_protocol.SESSION_QUERY_IN])
    worker = workers.KeyboardWorker(
        "/dev/hidraw7", kb_protocol.build_dongle_handshake(), dongle=True)
    with patch.object(workers, "HidrawTransport", lambda *a, **k: fake):
        results = _run(worker)

    assert results["finished"] == (True, "ok")


def test_keyboard_worker_dongle_fails_on_mismatched_reply():
    wrong = bytearray(kb_protocol.SESSION_QUERY_IN)
    wrong[-1] ^= 0xFF
    fake = FakeHidraw(read_replies=[kb_protocol.SESSION_INIT_IN, bytes(wrong)])
    worker = workers.KeyboardWorker(
        "/dev/hidraw7", kb_protocol.build_dongle_handshake(), dongle=True)
    with patch.object(workers, "HidrawTransport", lambda *a, **k: fake):
        results = _run(worker)

    assert results["finished"][0] is False
    assert "not acked" in results["finished"][1]


def test_keyboard_worker_cable_handshake_still_acks():
    fake = FakeHidraw(feature_replies=[
        _cable_ack(kb_protocol.OP_BEGIN), _cable_ack(kb_protocol.OP_END)])
    worker = workers.KeyboardWorker("/dev/hidraw0", kb_protocol.build_cable_handshake())
    with patch.object(workers, "HidrawTransport", lambda *a, **k: fake):
        results = _run(worker)

    assert results["finished"] == (True, "ok")
    assert fake.feature_payloads == [
        bytes([kb_protocol.REPORT_ID]) + kb_protocol.build_command(kb_protocol.OP_BEGIN),
        bytes([kb_protocol.REPORT_ID]) + kb_protocol.build_command(kb_protocol.OP_END),
    ]
