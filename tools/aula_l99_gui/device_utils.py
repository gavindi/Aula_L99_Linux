"""Device enumeration and error-hint text shared by both tabs."""
from __future__ import annotations

from aula_l99_hacky.device import HidrawDevice, VENDOR_INTERFACE, enumerate_hidraw
from aula_l99_screen.device import SerialDevice, enumerate_serial

KEYBOARD_PERMISSION_HINT = (
    "no access to the hidraw node; add a udev rule or run as root"
)
SCREEN_PERMISSION_HINT = (
    "no access to the serial port; add yourself to the 'dialout' group"
)


def list_keyboard_candidates() -> list[HidrawDevice]:
    """Same interface filter as find_l99(), but returns every match instead
    of just the first, for combo-box population."""
    return [
        d for d in enumerate_hidraw()
        if (d.is_cable or d.is_dongle) and d.interface_number == VENDOR_INTERFACE
    ]


def describe_keyboard(d: HidrawDevice) -> str:
    kind = "cable" if d.is_cable else "dongle" if d.is_dongle else "?"
    return f"{d.path}  {d.vendor_id:04x}:{d.product_id:04x}  ({kind})"


def list_screen_devices() -> list[SerialDevice]:
    return enumerate_serial()


def describe_screen(d: SerialDevice) -> str:
    vid = f"{d.vendor_id:04x}" if d.vendor_id is not None else "????"
    pid = f"{d.product_id:04x}" if d.product_id is not None else "????"
    tag = "  (AULA L99 touchscreen)" if d.is_screen else ""
    return f"{d.path}  {vid}:{pid}{tag}"
