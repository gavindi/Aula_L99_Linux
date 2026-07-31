"""Host-side lighting animations, and the mode table the User Lighting tab
offers.

Why these exist at all: the keyboard's built-in effects (`OP_EFFECT`, 0x13)
are *whole-keyboard* modes. Nothing in the protocol selects an effect for one
key -- no capture has ever shown such a thing, and the effect block has no key
field to put one in. So "animate this one key" cannot be asked of the
firmware; it has to be computed here and pushed over the realtime colour
stream (`OP_COLOR_STREAM`, 0x20) one frame at a time, which is exactly what
the vendor app was doing in save_to_gif_18.pcapng -- 245 frames animating key
0x73 and nothing else (see aula_l99_hacky/re_notes/color_stream.md).

Each animator is a pure function of (phase, position, rgb): testable with no
device, and safe to call from the stream worker's thread, which must not touch
widgets.

The colours here are what these effect names look like *on this side*. They
are not reproductions of the firmware's own effects -- nothing can read those
out -- so a mode applied to the whole keyboard (firmware) and the same mode
applied to one key (here) will not match beyond the name.
"""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass
from typing import Callable

from aula_l99_hacky import protocol as kb_protocol

from . import key_layout

Position = tuple[float, float]
Rgb = tuple[int, int, int]
Animator = Callable[[float, Position, Rgb], Rgb]

# Normalised key centres, (0.0, 0.0) top-left to (1.0, 1.0) bottom-right, off
# the same layout XML the overlay draws with. The position-dependent effects
# (wave, currents, revolving) need geometry, and this is the only place the
# project has any.
KEY_POSITIONS: dict[int, Position] = {
    key_id: (
        (rect.left + rect.width / 2) / key_layout.LAYOUT_WIDTH,
        (rect.top + rect.height / 2) / key_layout.LAYOUT_HEIGHT,
    )
    for key_id, rect in key_layout.KEY_RECTS.items()
}

# The device's speed byte is 1..5 with no known unit behind it. These are the
# host-side cycles per second that the same 1..5 picks for the animators below
# -- chosen to look right, not to match the firmware, which nothing here can
# measure.
SPEED_HZ = {1: 0.15, 2: 0.25, 3: 0.40, 4: 0.65, 5: 1.00}

# Fraction of a cycle a travelling band ("Following Currents") stays lit for,
# and a twinkle's ("Starlight") decay length. Both are looks, not protocol.
BAND_WIDTH = 0.25
TWINKLE_DECAY = 0.35


def _scale(rgb: Rgb, level: float) -> Rgb:
    level = min(max(level, 0.0), 1.0)
    return tuple(round(channel * level) for channel in rgb)


def _hue_rgb(hue: float, level: float = 1.0) -> Rgb:
    red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, 1.0, min(max(level, 0.0), 1.0))
    return (round(red * 255), round(green * 255), round(blue * 255))


def _key_noise(position: Position) -> float:
    """A stable per-key value in 0..1, so Starlight twinkles each key on its
    own schedule without carrying any state between frames."""
    x, y = position
    return math.modf(math.sin(x * 12.9898 + y * 78.233) * 43758.5453)[0] % 1.0


# -- animators ------------------------------------------------------------
# phase is in cycles (elapsed seconds x SPEED_HZ), unwrapped; position is a
# normalised key centre; rgb is whatever colour the tab's picker holds.


def breathing(phase: float, _position: Position, rgb: Rgb) -> Rgb:
    return _scale(rgb, 0.5 - 0.5 * math.cos(2 * math.pi * phase))


def colour_cycle(phase: float, _position: Position, _rgb: Rgb) -> Rgb:
    # Cycles its own hues, like the firmware's "colourful" -- the picker's
    # colour has nothing to contribute, so it is ignored rather than tinted in.
    return _hue_rgb(phase)


def rainbow_wave(phase: float, position: Position, _rgb: Rgb) -> Rgb:
    return _hue_rgb(phase - position[0])


def currents(phase: float, position: Position, rgb: Rgb) -> Rgb:
    distance = (phase - position[0]) % 1.0
    # Distance to the band's centre the short way round, so the band wraps off
    # the right edge back onto the left instead of restarting.
    distance = min(distance, 1.0 - distance)
    return _scale(rgb, 1.0 - distance / BAND_WIDTH)


def revolving(phase: float, position: Position, _rgb: Rgb) -> Rgb:
    x, y = position
    angle = math.atan2(y - 0.5, x - 0.5) / (2 * math.pi)
    return _hue_rgb(angle + phase)


def starlight(phase: float, position: Position, rgb: Rgb) -> Rgb:
    fraction = (phase + _key_noise(position)) % 1.0
    return _scale(rgb, 1.0 - fraction / TWINKLE_DECAY)


@dataclass(frozen=True)
class LightingMode:
    """One row of the tab's mode list.

    `effect_id` is the built-in effect a whole-keyboard apply selects, or None
    for a mode the firmware has no equivalent of (Starlight), which is then
    animated from here across all 84 keys instead.

    `animator` is what a single-key apply streams. None means the mode does not
    move at all -- those go down the persistent colour-write path instead of
    holding a stream open forever, writing `static_rgb`, or the picker's colour
    when that is None.
    """

    name: str
    effect_id: int | None
    animator: Animator | None
    static_rgb: Rgb | None = None

    @property
    def animates(self) -> bool:
        return self.animator is not None


# The names are the vendor app's; the ids after them were read off the app's
# own effect list order, so only the EFFECT_CONFIRMED subset is more than a
# guess. Starlight is in the vendor list with no id that works here, hence the
# host-side animator and no effect_id.
LIGHTING_MODES = (
    LightingMode("Static On", 0x01, None),
    LightingMode("Starlight", None, starlight),
    LightingMode("Dynamic Breathing", 0x07, breathing),
    LightingMode("Colourful Fountain", 0x06, colour_cycle),
    LightingMode("Rainbow Wave", 0x08, rainbow_wave),
    LightingMode("Following Currents", 0x0A, currents),
    LightingMode("Peak Revolving", 0x0C, revolving),
    LightingMode("Turn Off Lighting", 0x14, None, static_rgb=(0, 0, 0)),
)
MODE_BY_NAME = {mode.name: mode for mode in LIGHTING_MODES}


def build_frame(
    base_colors: dict[int, Rgb],
    animated_keys: set[int],
    animator: Animator,
    rgb: Rgb,
    elapsed: float,
    speed: int = kb_protocol.EFFECT_SPEED_DEFAULT,
) -> dict[int, Rgb]:
    """One frame: every key at its base colour, `animated_keys` at the
    animator's.

    Always returns the full 84-key table, because a stream frame carries all of
    them -- a key left out of `base_colors` is transmitted as off, there being
    no "leave this one alone" on the wire.
    """
    phase = elapsed * SPEED_HZ.get(speed, SPEED_HZ[kb_protocol.EFFECT_SPEED_DEFAULT])
    colors = {
        key_id: base_colors.get(key_id, (0, 0, 0)) for key_id in kb_protocol.KEY_IDS
    }
    for key_id in animated_keys:
        position = KEY_POSITIONS.get(key_id)
        if position is not None:
            colors[key_id] = animator(phase, position, rgb)
    return colors
