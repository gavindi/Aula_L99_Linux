"""Background-thread workers wrapping the keyboard/screen device I/O.

Reimplements the transaction-running and packet-sending loops from each
tool's cli.py (aula_l99_hacky/cli.py's _run_cable/_run_sequence and
aula_l99_screen/cli.py's cmd_upload send loop) against the public
protocol.py/device.py API, emitting Qt signals instead of printing, so the
GUI thread never blocks on hidraw feature-report or serial I/O.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, Signal, Slot

from aula_l99_hacky import protocol as kb_protocol
from aula_l99_hacky.device import HidrawTransport
from aula_l99_screen import protocol as screen_protocol
from aula_l99_screen.device import SerialTransport


def start_worker(worker: QObject) -> QThread:
    """Move `worker` onto a new QThread and start it.

    `worker.finished` only means the *work* is done -- the thread's event
    loop hasn't been told to quit yet at that point, let alone actually
    stopped. Caller must keep a reference to both `worker` and the
    returned thread alive until `thread.finished` fires (not
    `worker.finished`): that's the only signal Qt guarantees means the
    thread has actually stopped running. Dropping the Python reference to
    a QThread that's still alive lets it get garbage-collected while
    running, which Qt treats as fatal ("QThread: Destroyed while thread
    ... is still running") and aborts the process.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread


class KeyboardWorker(QObject):
    """Runs a list of kb_protocol.Transaction over HidrawTransport, cable
    path only -- mirrors cli.py's _run_cable/_run_sequence but signal-driven."""

    progress = Signal(int, int, str, bool)  # index, total, name, acked
    finished = Signal(bool, str)  # success, message

    def __init__(self, device_path: str, transactions: list,
                 timeout: float = 1.0, gap: float = kb_protocol.PACKET_GAP_SECONDS):
        super().__init__()
        self._device_path = device_path
        self._transactions = transactions
        self._timeout = timeout
        self._gap = gap

    @Slot()
    def run(self) -> None:
        try:
            failures = 0
            total = len(self._transactions)
            with HidrawTransport(self._device_path, timeout_seconds=self._timeout) as transport:
                for i, tx in enumerate(self._transactions):
                    attempts = kb_protocol.SESSION_OPEN_RETRIES if tx.retry_until_ack else 1
                    acked = True
                    for attempt in range(1, attempts + 1):
                        transport.set_feature(bytes([kb_protocol.REPORT_ID]) + tx.outgoing)
                        time.sleep(self._gap)
                        if tx.expect_reply:
                            reply = transport.get_feature(
                                kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)[1:]
                            time.sleep(self._gap)
                            acked = (
                                reply[0] == kb_protocol.CMD_PREFIX
                                and reply[1] == tx.outgoing[1]
                                and bool(reply[kb_protocol.ACK_OFFSET] & kb_protocol.ACK_FLAG)
                            )
                        else:
                            acked = True
                        if acked or attempt == attempts:
                            break
                        time.sleep(kb_protocol.RETRY_DELAY_SECONDS)
                    if tx.expect_reply and not acked:
                        failures += 1
                    self.progress.emit(i, total, tx.name, acked)
            self.finished.emit(
                failures == 0,
                "ok" if failures == 0 else f"{failures} transaction(s) not acked",
            )
        except (FileNotFoundError, PermissionError, TimeoutError, OSError) as exc:
            self.finished.emit(False, str(exc))


class ScreenUploadWorker(QObject):
    """Sends a pre-built list of packets over SerialTransport -- mirrors
    cli.py's cmd_upload send loop but signal-driven."""

    progress = Signal(int, int, int)  # sent, total, acked
    finished = Signal(bool, str)

    def __init__(self, device_path: str, packets: list[bytes], gap: float = 0.005):
        super().__init__()
        self._device_path = device_path
        self._packets = packets
        self._gap = gap

    @Slot()
    def run(self) -> None:
        try:
            sent = acked = 0
            total = len(self._packets)
            with SerialTransport(self._device_path) as transport:
                for i, packet in enumerate(self._packets):
                    transport.write(packet)
                    sent += 1
                    reply = transport.read_reply()
                    if screen_protocol.is_ack(packet[4], reply):
                        acked += 1
                    else:
                        self.finished.emit(
                            False,
                            f"packet {i} not acked; stopping (leaving the transfer "
                            f"incomplete can freeze the panel -- power-cycle it)",
                        )
                        return
                    if i % 25 == 0 or i == total - 1:
                        self.progress.emit(sent, total, acked)
                    time.sleep(self._gap)
            self.finished.emit(acked == sent, f"{sent} packets sent, {acked} acked")
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self.finished.emit(False, str(exc))
