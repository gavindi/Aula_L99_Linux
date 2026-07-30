"""Split the vendor sprite sheets in assets/skins/theme1 into per-state PNGs.

The vendor ships each widget as one horizontal strip of equally sized frames
(and two as vertical strips). Qt stylesheets can only point at a whole file,
never a sub-rectangle of one, so every state the QSS references has to exist as
its own image. This script writes those into `assets/skins/theme1/slices/`.

Run it after changing anything under `assets/skins/theme1/`; the output is
committed, so a normal run of the GUI never needs it:

    cd tools && python3 -m aula_l99_gui.slice_skin

Frame order was determined empirically from the sheets themselves -- the 4-frame
strips are uniformly [normal, hover, pressed, disabled], with hover at #EF6C00
and pressed at the darker #CF4D00. The 8-frame check/radio strips interleave an
unchecked and a checked set; see CHECK_FRAMES for the mapping.
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image

THEME_DIR = pathlib.Path(__file__).resolve().parent / "assets" / "skins" / "theme1"
SLICE_DIR = THEME_DIR / "slices"

STATES4 = ("normal", "hover", "pressed", "disabled")

# name -> (subdirectory, state names in frame order)
HORIZONTAL = {
    "btn_apply.png": (".", STATES4),
    "img_combobox.png": (".", STATES4),
    "img_edit.png": (".", STATES4),
    "main_sysbtn_close.png": (".", STATES4),
    "main_sysbtn_min.png": (".", STATES4),
    "img_thumb.png": (".", STATES4),
    "icon/tab_home.png": ("icon", STATES4),
    "icon/tab_customkey.png": ("icon", STATES4),
    "icon/tab_light.png": ("icon", STATES4),
    "icon/tab_userlight.png": ("icon", STATES4),
    "icon/tab_tft.png": ("icon", STATES4),
    "icon/tab_config.png": ("icon", STATES4),
}

# Vertical strips: name -> state names, top to bottom.
VERTICAL = {
    "img_slider_back.png": ("chunk", "groove"),
    "img_scroll_v.png": ("normal", "hover", "pressed"),
}

# The 8-frame check/radio strips hold two 4-state sets, interleaved rather than
# laid out back to back. Frames 4 and 6 duplicate the artwork of 2 and 1, which
# is why "pressed" reuses them.
CHECK_FRAMES = {
    "unchecked_normal": 0,
    "unchecked_hover": 1,
    "unchecked_pressed": 6,
    "unchecked_disabled": 3,
    "checked_normal": 2,
    "checked_hover": 5,
    "checked_pressed": 4,
    "checked_disabled": 7,
}
CHECK_SHEETS = ("btn_checkbox.png", "btn_radiobox.png")


def _save(image: Image.Image, stem: str, state: str) -> None:
    SLICE_DIR.mkdir(parents=True, exist_ok=True)
    image.save(SLICE_DIR / f"{stem}_{state}.png")


def main() -> int:
    if not THEME_DIR.is_dir():
        print(f"no theme directory at {THEME_DIR}", file=sys.stderr)
        return 1

    # Clear first so the output is exactly what the tables below describe --
    # dropping a sheet (or renaming one, as tab_config -> tab_home) would
    # otherwise leave orphaned slices behind that nothing references.
    removed = 0
    if SLICE_DIR.is_dir():
        for stale in SLICE_DIR.glob("*.png"):
            stale.unlink()
            removed += 1

    written = 0

    for name, (_, states) in HORIZONTAL.items():
        path = THEME_DIR / name
        with Image.open(path) as sheet:
            sheet = sheet.convert("RGBA")
            width = sheet.width // len(states)
            for i, state in enumerate(states):
                frame = sheet.crop((i * width, 0, (i + 1) * width, sheet.height))
                _save(frame, pathlib.Path(name).stem, state)
                written += 1

    for name, states in VERTICAL.items():
        with Image.open(THEME_DIR / name) as sheet:
            sheet = sheet.convert("RGBA")
            height = sheet.height // len(states)
            for i, state in enumerate(states):
                frame = sheet.crop((0, i * height, sheet.width, (i + 1) * height))
                _save(frame, pathlib.Path(name).stem, state)
                written += 1

    for name in CHECK_SHEETS:
        with Image.open(THEME_DIR / name) as sheet:
            sheet = sheet.convert("RGBA")
            width = sheet.width // 8
            for state, index in CHECK_FRAMES.items():
                frame = sheet.crop((index * width, 0, (index + 1) * width, sheet.height))
                _save(frame, pathlib.Path(name).stem, state)
                written += 1

    print(f"wrote {written} slices to {SLICE_DIR} (removed {removed} stale)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
