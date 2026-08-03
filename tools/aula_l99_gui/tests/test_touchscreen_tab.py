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
    CLIP_FULL,
    SourceImage,
    _crop_box,
    _evenly_spaced_indices,
    _per_source_frame_budget,
    _sane_clip,
    _source_from_csv_row,
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


# -- clip regions ------------------------------------------------------
#
# Clips are fractions of the source, so the same numbers describe a .png, a
# .gif and an .mp4. Everything below guards the two ways that can go wrong:
# a clip that escapes the source, and a clip that collapses to nothing.


def test_an_untouched_source_is_the_whole_image():
    assert SourceImage("a.png").clip == CLIP_FULL


def test_the_full_clip_skips_cropping_entirely():
    # None is the signal to leave the image alone -- both faster and what
    # keeps an unclipped upload byte-for-byte what it was before clipping.
    assert _crop_box(CLIP_FULL, 1920, 1080) is None


def test_a_clip_maps_to_source_pixels():
    assert _crop_box((0.25, 0.5, 0.5, 0.5), 800, 600) == (200, 300, 600, 600)


def test_a_clip_never_runs_past_the_source():
    left, top, right, bottom = _crop_box((0.9, 0.9, 0.2, 0.2), 100, 100)
    assert right <= 100 and bottom <= 100
    assert left < right and top < bottom


def test_a_tiny_clip_still_yields_a_pixel():
    # Rounding a sub-pixel clip to nothing gives Pillow a 0-wide image, which
    # then fails to resize -- so the box is widened rather than collapsed.
    left, top, right, bottom = _crop_box((0.5, 0.5, 0.001, 0.001), 10, 10)
    assert right > left and bottom > top


def test_a_clip_is_clamped_back_inside_the_source():
    assert _sane_clip((-0.5, 0.0, 2.0, 1.0)) == (0.0, 0.0, 1.0, 1.0)
    x, y, w, h = _sane_clip((0.8, 0.8, 0.9, 0.9))
    assert x + w <= 1.0 and y + h <= 1.0


def test_a_clip_is_never_zero_sized():
    _, _, w, h = _sane_clip((0.0, 0.0, 0.0, -1.0))
    assert w > 0 and h > 0


def test_a_saved_row_round_trips_its_clip():
    source = SourceImage("a.gif", 0.1, 0.2, 0.3, 0.4)
    row = ["a.gif", "50"] + [f"{v:.6g}" for v in source.clip]
    assert _source_from_csv_row(row).clip == source.clip


def test_a_row_from_before_clipping_loads_as_the_whole_source():
    # Saves written by earlier versions have only path and delay; they must
    # keep working rather than being dropped from the list.
    assert _source_from_csv_row(["a.gif", "50"]).clip == CLIP_FULL


def test_a_mangled_clip_falls_back_to_the_whole_source():
    assert _source_from_csv_row(["a.gif", "50", "x", "y", "z", "w"]).clip == CLIP_FULL
