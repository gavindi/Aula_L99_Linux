"""Small pure-function tests around the Device tab: the connection-kind
classification that drives the title-bar badge, and the badge's icon path."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aula_l99_gui import theme
from aula_l99_gui.device_tab import _connection_kind


def test_connection_kind_dongle():
    device = SimpleNamespace(is_cable=False, is_dongle=True)
    assert _connection_kind(device) == "dongle"


def test_connection_kind_cable():
    device = SimpleNamespace(is_cable=True, is_dongle=False)
    assert _connection_kind(device) == "cable"


def test_connection_kind_other_device():
    device = SimpleNamespace(is_screen=True)
    assert _connection_kind(device) == "screen"


def test_connection_icon_maps_dongle_to_24g():
    assert theme.connection_icon("dongle") == theme.DONGLE_MODE_ICON
    assert theme.connection_icon("dongle").name == "24g_mode.png"


def test_connection_icon_defaults_to_usb():
    assert theme.connection_icon("cable") == theme.USB_MODE_ICON
    assert theme.connection_icon("") == theme.USB_MODE_ICON
