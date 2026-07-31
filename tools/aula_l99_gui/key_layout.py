"""Per-key pixel rects for the keyboard layout image, parsed from the vendor
layout XML (`assets/layouts/rgb-keyboard.xml`).

`light_index` in the XML is the same integer as `key_id` in
aula_l99_hacky.protocol.KEY_IDS -- verified directly (same 84 values, just hex
vs decimal) rather than assumed, since nothing else in the codebase asserts
that connection.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from aula_l99_hacky import protocol as kb_protocol

from . import theme


@dataclass(frozen=True)
class KeyRect:
    key_id: int
    name: str
    left: int
    top: int
    width: int
    height: int


def _parse(path) -> tuple[int, int, dict[int, KeyRect], dict[int, int]]:
    root = ET.parse(path).getroot()
    keyboard = root.find("Keyboard")
    width = int(keyboard.get("width"))
    height = int(keyboard.get("height"))

    rects: dict[int, KeyRect] = {}
    hid_by_key_id: dict[int, int] = {}
    for key in keyboard.find("KeyItems").findall("key"):
        key_id = int(key.get("light_index"))
        rects[key_id] = KeyRect(
            key_id=key_id,
            name=key.get("name"),
            left=int(key.get("rect_left")),
            top=int(key.get("rect_top")),
            width=int(key.get("rect_width")),
            height=int(key.get("rect_height")),
        )
        hid_by_key_id[key_id] = int(key.get("code"), 16)
    return width, height, rects, hid_by_key_id


LAYOUT_WIDTH, LAYOUT_HEIGHT, KEY_RECTS, HID_BY_KEY_ID = _parse(theme.LAYOUT_XML)

# The vendor's saved-lighting XML identifies keys by `code` (the HID usage
# code) rather than by light_index, so anything reading those files has to come
# back through here. The two are one-to-one across all 84 keys.
KEY_ID_BY_HID = {hid: key_id for key_id, hid in HID_BY_KEY_ID.items()}

assert set(KEY_RECTS) == set(kb_protocol.KEY_IDS), (
    "rgb-keyboard.xml's light_index set no longer matches protocol.KEY_IDS"
)
assert len(KEY_ID_BY_HID) == len(HID_BY_KEY_ID), (
    "rgb-keyboard.xml has duplicate key codes -- HID <-> key_id is no longer one-to-one"
)
