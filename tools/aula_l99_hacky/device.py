"""Linux hidraw discovery and I/O for the AULA L99 keyboard's vendor HID channel."""
from __future__ import annotations

import fcntl
import os
import select
import time
from dataclasses import dataclass
from pathlib import Path

CABLE_VID = 0x0C45
CABLE_PID = 0x800A
DONGLE_VID = 0x05AC
DONGLE_PID = 0x024F
VENDOR_INTERFACE = 3  # confirmed by prior art (F75_Initializer) for both cable and dongle


@dataclass(frozen=True)
class HidrawDevice:
    path: str
    vendor_id: int | None
    product_id: int | None
    interface_number: int | None
    name: str | None

    @property
    def is_cable(self) -> bool:
        return self.vendor_id == CABLE_VID and self.product_id == CABLE_PID

    @property
    def is_dongle(self) -> bool:
        return self.vendor_id == DONGLE_VID and self.product_id == DONGLE_PID


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _walk_up_for_file(start: Path, filename: str) -> str | None:
    for candidate in (start, *start.parents):
        value = _read_text(candidate / filename)
        if value:
            return value
    return None


def _parse_hid_id(uevent: str | None) -> tuple[int | None, int | None]:
    if not uevent:
        return (None, None)
    for line in uevent.splitlines():
        if line.startswith("HID_ID="):
            _, value = line.split("=", 1)
            parts = value.split(":")
            if len(parts) == 3:
                try:
                    return (int(parts[1], 16), int(parts[2], 16))
                except ValueError:
                    pass
    return (None, None)


def enumerate_hidraw() -> list[HidrawDevice]:
    devices: list[HidrawDevice] = []
    for sys_node in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        device_dir = sys_node / "device"
        uevent = _read_text(device_dir / "uevent")
        vendor_id, product_id = _parse_hid_id(uevent)

        interface_raw = _walk_up_for_file(device_dir.resolve(), "bInterfaceNumber")
        interface_number = int(interface_raw, 16) if interface_raw else None

        name = None
        if uevent:
            for line in uevent.splitlines():
                if line.startswith("HID_NAME="):
                    _, name = line.split("=", 1)
                    break

        devices.append(
            HidrawDevice(
                path=str(Path("/dev") / sys_node.name),
                vendor_id=vendor_id,
                product_id=product_id,
                interface_number=interface_number,
                name=name,
            )
        )
    return devices


def find_l99(interface: int = VENDOR_INTERFACE) -> HidrawDevice:
    """Prefer the wired keyboard, fall back to the 2.4G dongle."""
    devices = enumerate_hidraw()
    for vid, pid in ((CABLE_VID, CABLE_PID), (DONGLE_VID, DONGLE_PID)):
        for device in devices:
            if device.vendor_id == vid and device.product_id == pid and device.interface_number == interface:
                return device
    raise FileNotFoundError(
        f"no AULA L99 vendor HID interface found (looked for interface {interface} "
        f"on {CABLE_VID:04x}:{CABLE_PID:04x} or {DONGLE_VID:04x}:{DONGLE_PID:04x})"
    )


def _ioctl_code(direction: int, ioc_type: int, nr: int, size: int) -> int:
    return (direction << 30) | (ioc_type << 8) | nr | (size << 16)


class HidrawTransport:
    """Raw read/write plus HID feature-report get/set via /dev/hidrawN."""

    def __init__(self, path: str, timeout_seconds: float = 1.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._fd: int | None = None

    def __enter__(self) -> "HidrawTransport":
        self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        return self

    def __exit__(self, *_exc) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def write(self, payload: bytes) -> int:
        assert self._fd is not None
        return os.write(self._fd, payload)

    def read_report(self, max_length: int = 64) -> bytes:
        assert self._fd is not None
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for a report from {self.path}")
            readable, _, _ = select.select([self._fd], [], [], remaining)
            if readable:
                report = os.read(self._fd, max_length)
                if report:
                    return report

    def drain(self, max_reads: int = 32) -> list[bytes]:
        assert self._fd is not None
        drained = []
        for _ in range(max_reads):
            readable, _, _ = select.select([self._fd], [], [], 0)
            if not readable:
                break
            report = os.read(self._fd, 64)
            if not report:
                break
            drained.append(report)
        return drained

    def set_feature(self, report: bytes) -> None:
        """HIDIOCSFEATURE"""
        assert self._fd is not None
        request = _ioctl_code(3, ord("H"), 0x06, len(report))
        fcntl.ioctl(self._fd, request, bytearray(report), True)

    def get_feature(self, report_id: int, size: int) -> bytes:
        """HIDIOCGFEATURE"""
        assert self._fd is not None
        request = _ioctl_code(3, ord("H"), 0x07, size)
        buffer = bytearray(size)
        buffer[0] = report_id
        fcntl.ioctl(self._fd, request, buffer, True)
        return bytes(buffer)
