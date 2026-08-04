"""Upload-argument validation for the screen CLI.

These arguments decide what gets written where in the panel's flash, and the
panel acks whatever it is given -- a bad `--address` or an oversized
`--width`/`--height` does not fail, it succeeds at writing over something
else. So they are checked before anything is built, and this is where that
is pinned down.
"""
from pathlib import Path
import sys

import pytest

# cli.py uses relative imports, so unlike test_protocol.py's bare
# `import protocol` (conftest puts the package dir on the path) this has to
# reach it as part of its package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aula_l99_screen import cli, protocol


def _args(**overrides):
    parser = cli.build_parser()
    args = parser.parse_args(["--upload", "x.png"])
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


# --- --address -------------------------------------------------------------


def test_a_target_resolves_to_its_own_base_address():
    for target, address in cli.TARGET_ADDRESSES.items():
        assert cli._upload_address(_args(target=target)) == address


def test_an_address_wider_than_the_wire_field_is_refused():
    # build_packet's struct.pack(">I", ...) would raise struct.error, which
    # main() doesn't catch -- a traceback rather than a message.
    for address in (-1, 0x1_0000_0000):
        with pytest.raises(SystemExit):
            cli._upload_address(_args(address=address))


def test_an_unknown_address_needs_force():
    with pytest.raises(SystemExit, match="force-address"):
        cli._upload_address(_args(address=0x04200000))
    assert cli._upload_address(_args(address=0x04200000, force_address=True)) == 0x04200000


def test_a_known_address_passes_without_force():
    assert (cli._upload_address(_args(address=protocol.GIF_FLASH_BASE))
            == protocol.GIF_FLASH_BASE)


# --- --width / --height ----------------------------------------------------


def test_the_panels_own_size_is_accepted():
    cli._check_dimensions(_args())


def test_dimensions_past_the_panel_need_force():
    # --height 960 is the concrete case: 614411 bytes, whose final chunk
    # length happens to be a solved CRC_INIT entry, so every packet of it
    # built and acked while overwriting the start of the GIF slot.
    with pytest.raises(SystemExit, match="force-size"):
        cli._check_dimensions(_args(height=960))
    cli._check_dimensions(_args(height=960, force_size=True))


def test_non_positive_dimensions_are_refused_even_with_force():
    for overrides in ({"width": 0}, {"height": -1}):
        with pytest.raises(SystemExit):
            cli._check_dimensions(_args(force_size=True, **overrides))
