"""Finding and writing to the AULA L99 touchscreen's serial port."""
from __future__ import annotations

import os
import termios
from dataclasses import dataclass
from pathlib import Path

SCREEN_VID = 0xEEEF
SCREEN_PID = 0x268A


@dataclass(frozen=True)
class SerialDevice:
    path: str
    vendor_id: int | None
    product_id: int | None

    @property
    def is_screen(self) -> bool:
        return self.vendor_id == SCREEN_VID and self.product_id == SCREEN_PID


def _read_hex(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip(), 16)
    except (OSError, ValueError):
        return None


def enumerate_serial() -> list[SerialDevice]:
    """All tty devices backed by USB, with the VID/PID of the owning device."""
    devices: list[SerialDevice] = []
    for node in sorted(Path("/sys/class/tty").glob("tty*")):
        device_dir = node / "device"
        if not device_dir.exists():
            continue

        # Walk up from the interface to the USB device holding idVendor.
        vendor = product = None
        current = device_dir.resolve()
        for candidate in (current, *current.parents):
            if (candidate / "idVendor").exists():
                vendor = _read_hex(candidate / "idVendor")
                product = _read_hex(candidate / "idProduct")
                break
            if candidate.name == "sys":
                break
        if vendor is None:
            continue
        devices.append(SerialDevice(str(Path("/dev") / node.name), vendor, product))
    return devices


def find_screen() -> SerialDevice:
    for device in enumerate_serial():
        if device.is_screen:
            return device
    raise FileNotFoundError(
        f"no AULA L99 touchscreen found (looked for {SCREEN_VID:04x}:{SCREEN_PID:04x} "
        f"on a USB serial port). Is it plugged in?"
    )


class SerialTransport:
    """Binary-safe write access to the panel.

    The port MUST be put in raw mode. A tty in its default cooked mode mangles
    binary data: ONLCR rewrites every 0x0A to 0x0D 0x0A, and IXON software flow
    control swallows 0x11 and 0x13. A JPEG contains all three in quantity, so
    the panel would receive a corrupt image whose length no longer matches the
    header. Baud rate is left alone -- CDC-ACM ignores it.
    """

    def __init__(self, path: str, read_timeout_deciseconds: int = 5) -> None:
        self.path = path
        self.read_timeout_deciseconds = read_timeout_deciseconds
        self._fd: int | None = None
        self._saved_attrs = None

    def __enter__(self) -> "SerialTransport":
        self._fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY)
        try:
            self._saved_attrs = termios.tcgetattr(self._fd)
            self._set_raw()
        except termios.error:
            # Not a tty (or no line discipline); nothing to configure.
            self._saved_attrs = None
        return self

    def __exit__(self, *_exc) -> None:
        if self._fd is not None:
            if self._saved_attrs is not None:
                try:
                    termios.tcsetattr(self._fd, termios.TCSANOW, self._saved_attrs)
                except termios.error:
                    pass
            os.close(self._fd)
            self._fd = None

    def _set_raw(self) -> None:
        """The equivalent of cfmakeraw(), which Python does not expose."""
        assert self._fd is not None
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self._fd)
        iflag &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP
                   | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
        oflag &= ~termios.OPOST
        lflag &= ~(termios.ECHO | termios.ECHONL | termios.ICANON
                   | termios.ISIG | termios.IEXTEN)
        cflag &= ~(termios.CSIZE | termios.PARENB)
        cflag |= termios.CS8
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = self.read_timeout_deciseconds
        termios.tcsetattr(self._fd, termios.TCSANOW,
                          [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
        termios.tcflush(self._fd, termios.TCIOFLUSH)

    def write(self, payload: bytes, chunk_size: int = 4096) -> int:
        """Write in chunks; os.write may not consume a large buffer in one go."""
        assert self._fd is not None
        sent = 0
        while sent < len(payload):
            sent += os.write(self._fd, payload[sent:sent + chunk_size])
        try:
            termios.tcdrain(self._fd)
        except termios.error:
            pass
        return sent

    def read_reply(self, max_bytes: int = 256) -> bytes:
        """Read whatever the panel sends back, if anything. VTIME bounds the wait."""
        assert self._fd is not None
        try:
            return os.read(self._fd, max_bytes)
        except OSError:
            return b""
