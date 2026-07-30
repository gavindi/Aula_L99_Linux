import pytest

import protocol


def test_ramp_constants():
    assert protocol.RAMP_R == (0, 49, 99, 156, 206, 255)
    assert protocol.RAMP_G == (0, 40, 85, 130, 170, 215, 255)
    assert protocol.RAMP_B == protocol.RAMP_R


def test_nearest_ramp_value_known_points():
    assert protocol.nearest_ramp_value(0, protocol.RAMP_R) == 0
    assert protocol.nearest_ramp_value(255, protocol.RAMP_R) == 255
    assert protocol.nearest_ramp_value(60, protocol.RAMP_R) == 49
    assert protocol.nearest_ramp_value(75, protocol.RAMP_R) == 99
    assert protocol.nearest_ramp_value(-10, protocol.RAMP_G) == 0
    assert protocol.nearest_ramp_value(300, protocol.RAMP_G) == 255


def test_safe_colors_are_always_ramp_legal():
    for color in [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255)]:
        assert protocol.is_safe_gif_color(*color)
        assert protocol.is_ramp_legal_color(*color)


def test_non_ramp_color_is_not_ramp_legal():
    assert not protocol.is_ramp_legal_color(128, 128, 128)


def test_dither_output_is_always_ramp_legal():
    width, height = 32, 32
    pixels = [
        ((x * 8) % 256, (y * 8) % 256, ((x + y) * 4) % 256)
        for y in range(height) for x in range(width)
    ]
    out = protocol.dither_frame_floyd_steinberg(pixels, width)
    assert len(out) == len(pixels)
    for color in out:
        assert protocol.is_ramp_legal_color(*color)


def test_dither_frame_rejects_bad_width():
    with pytest.raises(ValueError):
        protocol.dither_frame_floyd_steinberg([(0, 0, 0)] * 10, width=3)


def test_build_gif_blob_flat_gray_rejected_without_dither():
    width, height = 128, 128
    frames = [[(128, 128, 128)] * (width * height)]
    with pytest.raises(ValueError):
        protocol.build_gif_blob(frames, width, height, delay=50, dither=False)


def test_build_gif_blob_flat_gray_succeeds_with_dither():
    # Half solid black (stays untouched by dithering -- black is already
    # ramp-legal -- giving the CRC-length-tuning pass a long run to pad
    # onto a valid chunk length) plus half solid mid-gray (exercises real
    # per-pixel dithering, which tends to alternate every 1-3px and so
    # can't supply that long run on its own).
    width, height = 128, 128
    n = width * height
    frames = [[(0, 0, 0)] * (n // 2) + [(128, 128, 128)] * (n - n // 2)]
    blob = protocol.build_gif_blob(frames, width, height, delay=50, dither=True)
    assert isinstance(blob, bytes)
    assert len(blob) > 0


def test_dither_false_is_unchanged_regression():
    width, height = 128, 128
    frames = [[(255, 0, 0)] * (width * height // 2) + [(0, 0, 0)] * (width * height // 2)]
    default_call = protocol.build_gif_blob(frames, width, height, delay=50)
    explicit_false = protocol.build_gif_blob(frames, width, height, delay=50, dither=False)
    assert default_call == explicit_false
