"""Frame budgeting for the Touchscreen tab's Customized Animation build.

The panel's format carries a one-byte frame count, so a long source has to
be sampled down before it reaches the encoder. Getting this wrong is not a
quality issue: a 4883-frame GIF previously spent minutes decoding and
writing a local copy, then failed on encode with "byte must be in
range(0, 256)".
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aula_l99_gui.touchscreen_tab import (
    _evenly_spaced_indices,
    _per_source_frame_budget,
)
from aula_l99_screen import protocol


def test_shorter_than_the_limit_keeps_every_frame():
    assert _evenly_spaced_indices(5, 200) == [0, 1, 2, 3, 4]


def test_exactly_the_limit_keeps_every_frame():
    assert _evenly_spaced_indices(200, 200) == list(range(200))


def test_longer_source_is_sampled_down_to_the_limit():
    kept = _evenly_spaced_indices(4883, 200)
    assert len(kept) == 200
    assert kept == sorted(set(kept))          # strictly increasing, no repeats
    assert kept[0] == 0
    assert max(kept) < 4883


def test_sampling_spans_the_whole_source():
    # Truncating to the opening 200 frames would leave max(kept) == 199;
    # the point of sampling is to represent the whole animation.
    kept = _evenly_spaced_indices(4883, 200)
    assert kept[-1] > 4883 * 0.98


def test_sampling_is_evenly_spaced():
    kept = _evenly_spaced_indices(1000, 100)
    gaps = {b - a for a, b in zip(kept, kept[1:])}
    assert gaps == {10}


def test_degenerate_inputs():
    assert _evenly_spaced_indices(0, 200) == []
    assert _evenly_spaced_indices(100, 0) == []


def test_budget_gives_a_lone_source_the_whole_allowance():
    assert _per_source_frame_budget(["a.gif"]) == protocol.MAX_GIF_FRAMES


def test_budget_splits_between_multi_frame_sources():
    # Evenly, not first-come-first-served: the second GIF must not be
    # squeezed out by whatever was listed ahead of it.
    assert _per_source_frame_budget(["a.gif", "b.mp4"]) == protocol.MAX_GIF_FRAMES // 2


def test_budget_ignores_still_images():
    assert _per_source_frame_budget(["a.gif", "b.png", "c.jpg"]) == protocol.MAX_GIF_FRAMES


def test_budget_never_reaches_zero():
    assert _per_source_frame_budget([f"{i}.gif" for i in range(500)]) >= 1


def test_budget_survives_stills_only():
    assert _per_source_frame_budget(["a.png"]) >= 1


def test_a_sampled_source_fits_what_the_format_can_carry():
    kept = _evenly_spaced_indices(4883, _per_source_frame_budget(["big.gif"]))
    assert len(kept) <= protocol.GIF_FRAME_COUNT_MAX
