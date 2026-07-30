import random
import struct

import pytest

import protocol


def _parse_frame_header(blob: bytes, frame_index: int):
    """Test helper: locate a frame via its TOC entry and read back its
    sub-header fields (mode_flag, size32, palette) plus the frame's
    absolute content offset/length.
    """
    toc_offset = 20 * frame_index
    frame_offset = struct.unpack_from("<I", blob, toc_offset)[0]
    size32 = struct.unpack_from("<I", blob, frame_offset + 8)[0]
    mode_flag = struct.unpack_from("<H", blob, frame_offset + 14)[0]
    content_length = size32 - protocol.GIF_FRAME_PREFIX_SIZE
    content_offset = frame_offset + protocol.GIF_FRAME_PREFIX_SIZE
    content = blob[content_offset:content_offset + content_length]
    return {
        "mode_flag": mode_flag,
        "size32": size32,
        "content": content,
        "header": blob[frame_offset:frame_offset + protocol.GIF_FRAME_PREFIX_SIZE],
    }


def _palette_rgb565(header: bytes, count: int) -> list[int]:
    return [struct.unpack_from("<H", header, 16 + i * 2)[0] for i in range(count)]


def _crc16_modbus_reference(data: bytes) -> int:
    """Bit-by-bit reference implementation, independent of the table-driven
    crc16_modbus(), to guard the table rewrite against ever drifting.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def test_crc16_modbus_matches_bit_by_bit_reference():
    rng = random.Random(1)
    for _ in range(20):
        data = bytes(rng.randint(0, 255) for _ in range(rng.randint(0, 500)))
        assert protocol.crc16_modbus(data) == _crc16_modbus_reference(data)


def test_ramp_lut_matches_nearest_ramp_value():
    for v in range(256):
        assert protocol.RAMP_R_LUT[v] == protocol.nearest_ramp_value(v, protocol.RAMP_R)
        assert protocol.RAMP_G_LUT[v] == protocol.nearest_ramp_value(v, protocol.RAMP_G)
        assert protocol.RAMP_B_LUT[v] == protocol.nearest_ramp_value(v, protocol.RAMP_B)


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


def test_gif_largest_run_skips_ineligible_frames():
    frames_runs = [
        [(1000, (0, 0, 0))],       # frame 0: the biggest run, but ineligible (raw-bitmap)
        [(50, (255, 255, 255))],   # frame 1: smaller run, eligible
    ]
    assert protocol._gif_largest_run(frames_runs, eligible={1}) == (1, 0, 50)
    # sanity: without the filter, frame 0's bigger run would win instead
    assert protocol._gif_largest_run(frames_runs) == (0, 0, 1000)


def test_gif_largest_run_returns_none_when_nothing_eligible():
    frames_runs = [[(1000, (0, 0, 0))]]
    assert protocol._gif_largest_run(frames_runs, eligible=set()) is None


def test_build_gif_blob_forces_raw_bitmap_for_oversized_rle_content():
    # Alternate between two safe colors every single pixel across the whole
    # frame -- every run is 1px, so RLE tokens cost 2 bytes/pixel. At
    # 300x120 = 36000 pixels that's 72000 content bytes, comfortably over
    # the 16-bit content-length field's 65535-byte range, forcing this
    # frame into raw-bitmap mode automatically. A second, solid-color frame
    # is included as a companion frame (no longer needed as a padding donor
    # now that raw-bitmap frames pad themselves via trailing filler).
    width, height = 300, 120
    n = width * height
    raw_frame = [(0, 0, 0) if i % 2 == 0 else (255, 255, 255) for i in range(n)]
    solid_frame = [(0, 255, 0)] * n
    blob = protocol.build_gif_blob([raw_frame, solid_frame], width, height, delay=50)
    parsed = _parse_frame_header(blob, 0)
    assert parsed["mode_flag"] == protocol.GIF_MODE_RAW_BITMAP
    # Content may be padded with trailing filler bytes to tune the total
    # upload length -- the true pixel data is always the first n bytes.
    assert len(parsed["content"]) >= n


def test_raw_bitmap_content_round_trips_to_original_pixels():
    width, height = 300, 120
    n = width * height
    pixels = [(0, 0, 0) if i % 2 == 0 else (255, 255, 255) for i in range(n)]
    solid_frame = [(0, 255, 0)] * n
    blob = protocol.build_gif_blob([pixels, solid_frame], width, height, delay=50)
    parsed = _parse_frame_header(blob, 0)
    assert parsed["mode_flag"] == protocol.GIF_MODE_RAW_BITMAP

    distinct_colors = len({parsed["content"][i] for i in range(n)})
    palette = _palette_rgb565(parsed["header"], distinct_colors)
    for i, original in enumerate(pixels):
        idx = parsed["content"][i]
        assert palette[idx] == protocol.rgb_to_rgb565(*original)


def test_build_gif_blob_small_content_still_uses_rle():
    width, height = 128, 128
    frames = [[(255, 0, 0)] * (width * height // 2) + [(0, 0, 0)] * (width * height // 2)]
    blob = protocol.build_gif_blob(frames, width, height, delay=50)
    parsed = _parse_frame_header(blob, 0)
    assert parsed["mode_flag"] == protocol.GIF_MODE_RLE


def test_mixed_rle_and_raw_bitmap_frames_build_successfully():
    # Frame 0 is forced into raw-bitmap mode (oversized RLE content); frame
    # 1 is a simple solid-color RLE frame with a big run. Confirms a mixed
    # upload builds successfully with the expected mode per frame.
    width, height = 300, 120
    n = width * height
    raw_frame = [(0, 0, 0) if i % 2 == 0 else (255, 255, 255) for i in range(n)]
    solid_frame = [(0, 255, 0)] * n
    blob = protocol.build_gif_blob([raw_frame, solid_frame], width, height, delay=50)

    parsed0 = _parse_frame_header(blob, 0)
    parsed1 = _parse_frame_header(blob, 1)
    assert parsed0["mode_flag"] == protocol.GIF_MODE_RAW_BITMAP
    assert len(parsed0["content"]) >= n
    assert parsed1["mode_flag"] == protocol.GIF_MODE_RLE


def test_raw_bitmap_frame_is_preferred_padding_donor_over_rle():
    # When both a raw-bitmap frame and an RLE frame with a large run are
    # present, padding should go to the raw-bitmap frame (unconstrained,
    # always works) rather than splitting the RLE frame's run.
    width, height = 300, 120
    n = width * height
    raw_frame = [(0, 0, 0) if i % 2 == 0 else (255, 255, 255) for i in range(n)]
    solid_frame = [(0, 255, 0)] * n
    blob = protocol.build_gif_blob([raw_frame, solid_frame], width, height, delay=50)

    parsed1 = _parse_frame_header(blob, 1)
    # A single 36000px run chains into ceil(36000/256) = 141 tokens (2
    # bytes each) when NOT split for padding -- if this matches exactly,
    # the RLE frame was left untouched and all padding went to frame 0.
    expected_unpadded_content_length = -(-n // 256) * 2
    assert len(parsed1["content"]) == expected_unpadded_content_length


def test_build_gif_blob_single_busy_frame_no_donor_needed_regression():
    # Regression test for a real reported bug: a single full-panel frame
    # with color/detail variation everywhere (no flat region anywhere)
    # forces raw-bitmap mode with no other frame to act as a padding
    # donor. Previously raised "no frame has a large enough solid/uniform
    # run... every frame is using raw-bitmap mode" -- should now succeed,
    # since the raw-bitmap frame pads itself.
    width, height = protocol.PANEL_WIDTH, protocol.PANEL_HEIGHT
    pixels = [
        ((x * 3) % 256, (y * 2) % 256, ((x + y) * 5) % 256)
        for y in range(height) for x in range(width)
    ]
    blob = protocol.build_gif_blob([pixels], width, height, delay=50, dither=True)
    parsed = _parse_frame_header(blob, 0)
    assert parsed["mode_flag"] == protocol.GIF_MODE_RAW_BITMAP
    assert len(parsed["content"]) >= width * height


def test_build_gif_blob_pads_to_a_valid_chunk_boundary():
    # Confirm the padded blob's length actually lands on a byte count
    # whose CHUNK_SIZE remainder is 0 or a solved CRC_INIT entry -- not
    # just that build_gif_blob happened not to raise.
    width, height = protocol.PANEL_WIDTH, protocol.PANEL_HEIGHT
    pixels = [
        ((x * 3) % 256, (y * 2) % 256, ((x + y) * 5) % 256)
        for y in range(height) for x in range(width)
    ]
    blob = protocol.build_gif_blob([pixels], width, height, delay=50, dither=True)
    remainder = len(blob) % protocol.CHUNK_SIZE
    assert remainder == 0 or remainder in protocol.CRC_INIT
