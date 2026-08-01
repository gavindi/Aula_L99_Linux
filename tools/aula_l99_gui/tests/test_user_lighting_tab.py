from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aula_l99_gui import stream_effects
from aula_l99_gui.user_lighting_tab import (
    merge_selected_key_colors,
    resolve_apply_colors,
)
from aula_l99_gui.workers import _read_colors_from_transport
from aula_l99_hacky import protocol as kb_protocol


class FakeTransport:
    def __init__(self, reply_batches: list[list[bytes]]):
        self._reply_batches = list(reply_batches)
        self._drain_calls = 0

    def drain(self):
        self._drain_calls += 1
        return []

    def set_feature(self, payload: bytes) -> None:
        self._payload = payload

    def get_feature(self, report_id: int, size: int) -> bytes:
        if not self._reply_batches:
            raise AssertionError("unexpected get_feature call")
        batch = self._reply_batches.pop(0)
        if not batch:
            raise AssertionError("missing queued reply")
        return batch.pop(0)


def test_merge_selected_key_colors_preserves_existing_keys():
    colors = {
        0x01: (1, 2, 3),
        0x02: (4, 5, 6),
        0x03: (7, 8, 9),
    }

    updated = merge_selected_key_colors(colors, 0x02, (10, 11, 12))

    assert updated[0x01] == (1, 2, 3)
    assert updated[0x02] == (10, 11, 12)
    assert updated[0x03] == (7, 8, 9)


def test_resolve_apply_colors_uses_cached_table_when_read_is_incomplete():
    fallback = {
        0x01: (1, 2, 3),
        0x02: (4, 5, 6),
        0x03: (7, 8, 9),
    }

    updated = resolve_apply_colors({}, 0x02, (10, 11, 12), fallback)

    assert updated[0x01] == (1, 2, 3)
    assert updated[0x02] == (10, 11, 12)
    assert updated[0x03] == (7, 8, 9)


def test_every_mode_offers_a_device_effect_or_a_host_animator():
    # A mode with neither would be a dead row in the list: nothing to select on
    # the keyboard, and nothing to animate a single key with either.
    for mode in stream_effects.LIGHTING_MODES:
        assert mode.effect_id is not None or mode.animator is not None, mode.name


def test_build_frame_animates_only_the_selected_keys():
    base = {key_id: (10, 20, 30) for key_id in kb_protocol.KEY_IDS}

    frame = stream_effects.build_frame(
        base, {0x01}, stream_effects.colour_cycle, (255, 0, 0), elapsed=0.0
    )

    assert set(frame) == set(kb_protocol.KEY_IDS)
    assert frame[0x01] != (10, 20, 30)
    assert all(frame[key_id] == (10, 20, 30) for key_id in kb_protocol.KEY_IDS if key_id != 0x01)


def test_build_frame_output_changes_over_time_for_every_animator():
    # The bug this whole path exists to fix was a single static frame, so what
    # matters is that consecutive frames actually differ.
    base = {key_id: (0, 0, 0) for key_id in kb_protocol.KEY_IDS}
    for mode in stream_effects.LIGHTING_MODES:
        if not mode.animates:
            continue
        frames = {
            stream_effects.build_frame(
                base, {0x01}, mode.animator, (255, 0, 0), elapsed=elapsed
            )[0x01]
            for elapsed in (0.0, 0.5, 1.0, 1.5)
        }
        assert len(frames) > 1, mode.name


def test_build_frame_keys_absent_from_the_base_table_are_off():
    frame = stream_effects.build_frame(
        {}, set(), stream_effects.breathing, (255, 0, 0), elapsed=0.0
    )

    assert set(frame) == set(kb_protocol.KEY_IDS)
    assert set(frame.values()) == {(0, 0, 0)}


def test_frames_are_valid_stream_input():
    # build_stream_blocks validates key ids and channel ranges, so this is what
    # catches an animator that returns something off-scale or out of gamut.
    base = {key_id: (0, 0, 0) for key_id in kb_protocol.KEY_IDS}
    for mode in stream_effects.LIGHTING_MODES:
        if not mode.animates:
            continue
        for elapsed in (0.0, 0.37, 1.23, 4.9):
            frame = stream_effects.build_frame(
                base, set(kb_protocol.KEY_IDS), mode.animator, (255, 128, 0), elapsed=elapsed
            )
            blocks = kb_protocol.build_stream_blocks(frame)
            assert len(blocks) == kb_protocol.STREAM_BLOCK_COUNT


def test_starlight_twinkles_keys_out_of_step_with_each_other():
    base = {key_id: (0, 0, 0) for key_id in kb_protocol.KEY_IDS}

    frame = stream_effects.build_frame(
        base, set(kb_protocol.KEY_IDS), stream_effects.starlight, (255, 255, 255), elapsed=1.0
    )

    assert len(set(frame.values())) > 1


def test_read_colors_falls_back_to_the_last_full_table_when_the_read_is_partial():
    fallback = {key_id: (1, 2, 3) for key_id in kb_protocol.KEY_IDS}
    reply_batches = []
    for _ in kb_protocol.build_color_query_commands():
        reply_batches.append([bytes([0x00, kb_protocol.CMD_PREFIX, 0x00, 0x01])])
    blocks = []
    for _ in range(kb_protocol.COLOR_BLOCK_COUNT):
        block = bytearray(64)
        block[0] = 0x01
        block[1:4] = b"\x01\x02\x03"
        blocks.append(bytes(block))
    reply_batches.append(blocks)
    transport = FakeTransport(reply_batches)

    colors = _read_colors_from_transport(transport, attempts=1, fallback=fallback)

    assert colors == fallback
