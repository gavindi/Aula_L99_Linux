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


# --- frame count: the TOC's count field is one byte ----------------------


def _solid(n, color=(255, 0, 0)):
    return [color] * (n // 2) + [(0, 0, 0)] * (n - n // 2)


def test_build_gif_blob_accepts_the_format_ceiling():
    width, height = 16, 16
    blob = protocol.build_gif_blob(
        [_solid(width * height)] * protocol.GIF_FRAME_COUNT_MAX, width, height, delay=50)
    # Byte 13 of the first TOC entry is the frame count -- the field that
    # used to blow up with "byte must be in range(0, 256)".
    assert blob[13] == protocol.GIF_FRAME_COUNT_MAX


def test_build_gif_blob_rejects_more_frames_than_the_field_can_hold():
    width, height = 16, 16
    frames = [_solid(width * height)] * (protocol.GIF_FRAME_COUNT_MAX + 1)
    with pytest.raises(ValueError, match="more than this format can carry"):
        protocol.build_gif_blob(frames, width, height, delay=50)


def test_build_gif_blob_rejects_no_frames():
    with pytest.raises(ValueError, match="no frames"):
        protocol.build_gif_blob([], 16, 16, delay=50)


def test_vendor_frame_limit_is_under_the_format_ceiling():
    assert protocol.MAX_GIF_FRAMES <= protocol.GIF_FRAME_COUNT_MAX


def test_vendor_blob_ceiling_admits_a_vendor_shaped_upload():
    # The largest thing the vendor's own encoder could build -- every frame
    # at the 16-bit content-length maximum -- must sit exactly at the
    # ceiling, not over it, or the warning would fire on legitimate uploads.
    largest_vendor_frame = (
        protocol.GIF_TOC_ENTRY_SIZE + protocol.GIF_FRAME_PREFIX_SIZE + 0xFFFF)
    assert (protocol.MAX_GIF_FRAMES * largest_vendor_frame
            == protocol.VENDOR_MAX_GIF_BLOB_BYTES)


def test_raw_bitmap_frames_can_exceed_the_vendor_blob_ceiling():
    # The case the warning exists for: raw-bitmap mode emits a fixed
    # width*height bytes per frame, well past what an RLE frame can reach.
    raw_frame = (protocol.GIF_TOC_ENTRY_SIZE + protocol.GIF_FRAME_PREFIX_SIZE
                 + protocol.PANEL_WIDTH * protocol.PANEL_HEIGHT)
    assert protocol.MAX_GIF_FRAMES * raw_frame > protocol.VENDOR_MAX_GIF_BLOB_BYTES


# --- CRC ------------------------------------------------------------------


def _crc16_packet_reference(body: bytes) -> int:
    """Bit-by-bit reference for crc16_packet(), same role as
    _crc16_modbus_reference() above -- the shipped one is table-driven."""
    crc = protocol.CRC_INIT[len(body) - protocol.HEADER_SIZE_WIRE]
    for byte in body:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def test_crc16_packet_matches_bit_by_bit_reference():
    rng = random.Random(2)
    for payload_len in sorted(protocol.CRC_INIT):
        body = bytes(rng.randint(0, 255)
                     for _ in range(protocol.HEADER_SIZE_WIRE + payload_len))
        assert protocol.crc16_packet(body) == _crc16_packet_reference(body)


def test_blob_carries_a_real_payload_crc():
    # The length-probing pass builds with with_crc=False; regression guard
    # against that zero-checksum blob ever being the one returned.
    width, height = 128, 128
    n = width * height
    blob = protocol.build_gif_blob([_solid(n)], width, height, delay=50)
    toc_crc = int.from_bytes(blob[18:20], "little")
    assert toc_crc == protocol.crc16_modbus(blob[20:])


# --- frame representation: bytes and list[(r,g,b)] are interchangeable ----


def _as_bytes(pixels) -> bytes:
    return bytes(channel for color in pixels for channel in color)


def test_bytes_frames_build_identical_blob_to_tuple_frames():
    width, height = 128, 128
    n = width * height
    frames = [_solid(n), [(0, 255, 0)] * n]
    from_tuples = protocol.build_gif_blob(frames, width, height, delay=50)
    from_bytes = protocol.build_gif_blob(
        [_as_bytes(f) for f in frames], width, height, delay=50)
    assert from_bytes == from_tuples


def test_bytes_and_tuple_frames_report_the_same_bad_colors():
    width, height = 32, 32
    n = width * height
    # Two unsafe pixels of one colour, one of another -- the message orders
    # by count, so this pins the counting, not just the detection.
    pixels = [(0, 0, 0)] * (n - 3) + [(7, 9, 11), (7, 9, 11), (3, 4, 5)]
    with pytest.raises(ValueError) as from_tuples:
        protocol.build_gif_blob([pixels], width, height, delay=50)
    with pytest.raises(ValueError) as from_bytes:
        protocol.build_gif_blob([_as_bytes(pixels)], width, height, delay=50)
    assert str(from_bytes.value) == str(from_tuples.value)
    assert "rgb(7, 9, 11): 2 pixels" in str(from_bytes.value)
    assert "rgb(3, 4, 5): 1 pixels" in str(from_bytes.value)


def test_build_gif_blob_rejects_wrong_length_bytes_frame():
    with pytest.raises(ValueError, match="expected 1024 pixels"):
        protocol.build_gif_blob([bytes(3 * 1000)], 32, 32, delay=50)


def test_build_gif_blob_does_not_mutate_the_callers_frame_list():
    width, height = 32, 32
    frames = [[(0, 0, 0)] * (width * height)]
    original = frames[0]
    protocol.build_gif_blob(frames, width, height, delay=50, dither=True)
    assert frames[0] is original


def test_gif_runs_accepts_both_frame_forms():
    pixels = [(0, 0, 0)] * 5 + [(255, 0, 0)] * 3
    expected = [(5, (0, 0, 0)), (3, (255, 0, 0))]
    assert protocol._gif_runs(pixels) == expected
    assert protocol._gif_runs(_as_bytes(pixels)) == expected


def test_gif_token_count_matches_building_the_tokens():
    # Spans the 256px chaining boundary both ways, since the shortcut has to
    # reproduce _gif_tokens()'s own chunking exactly.
    runs = [(1, (0, 0, 0)), (256, (255, 0, 0)), (257, (0, 255, 0)), (1000, (0, 0, 255))]
    palette_index = {color: i for i, (_length, color) in enumerate(runs)}
    assert protocol._gif_token_count(runs) == len(protocol._gif_tokens(runs, palette_index))


# --- dithering ------------------------------------------------------------


def test_dither_returns_the_form_it_was_given():
    width, height = 32, 32
    pixels = [((x * 8) % 256, (y * 8) % 256, ((x + y) * 4) % 256)
              for y in range(height) for x in range(width)]
    as_list = protocol.dither_frame_floyd_steinberg(pixels, width)
    as_bytes = protocol.dither_frame_floyd_steinberg(_as_bytes(pixels), width)
    assert isinstance(as_list, list) and isinstance(as_list[0], tuple)
    assert isinstance(as_bytes, bytes)
    assert _as_bytes(as_list) == as_bytes


def test_both_dither_paths_are_ramp_legal():
    """Pillow's pattern differs from the pure-Python fallback's, but the
    invariant every caller relies on holds for both."""
    width, height = 64, 64
    pixels = [((x * 5) % 256, (y * 7) % 256, ((x * y) % 256))
              for y in range(height) for x in range(width)]
    raw = _as_bytes(pixels)
    outputs = [bytes(protocol._dither_rgb_bytes(raw, width))]
    from_pillow = protocol._dither_rgb_pillow(raw, width, height)
    if from_pillow is not None:  # Pillow is optional for this module
        outputs.append(from_pillow)
    for out in outputs:
        assert len(out) == len(raw)
        for color in protocol._distinct_colors(out):
            assert protocol.is_ramp_legal_color(*color)


def test_dither_leaves_ramp_legal_regions_untouched():
    """build_gif_blob's CRC-length tuning needs a long uniform run to pad;
    dithering one away would break it, so neither path may disturb pixels
    already sitting on the ramp."""
    width, height = 64, 64
    for color in [(0, 0, 0), (255, 0, 0), (49, 40, 99)]:
        raw = bytes(color) * (width * height)
        assert bytes(protocol._dither_rgb_bytes(raw, width)) == raw
        from_pillow = protocol._dither_rgb_pillow(raw, width, height)
        if from_pillow is not None:
            assert from_pillow == raw


def test_ramp_colors_is_the_full_product():
    assert len(protocol.RAMP_COLORS) == len(protocol.RAMP_R) * len(protocol.RAMP_G) * len(protocol.RAMP_B)
    assert len(protocol.RAMP_COLORS) == len(set(protocol.RAMP_COLORS))
    for color in protocol.RAMP_COLORS:
        assert protocol.is_ramp_legal_color(*color)


# --- flash slot bounds -----------------------------------------------------


def test_an_upload_that_overruns_its_slot_is_refused():
    """The panel acks every packet of an oversized upload and writes the
    excess over whatever flash follows the slot, so build_upload is the only
    place this can be caught."""
    blob = b"\x00" * (protocol.SLOT_CAPACITY[protocol.PHOTO_FRAME_FLASH_BASE] + 1)
    with pytest.raises(ValueError, match="past"):
        protocol.build_upload(blob, protocol.PHOTO_FRAME_FLASH_BASE)


def test_an_ordinary_panel_sized_image_still_fits_every_image_slot():
    blob = protocol.build_image_file(
        b"\x00" * (protocol.PANEL_WIDTH * protocol.PANEL_HEIGHT * 3))
    for base in (protocol.PHOTO_FRAME_FLASH_BASE, protocol.BACKGROUND_FLASH_BASE):
        # 154 packets is what wireshark_dumps/save_to_bkg_1/2.pcapng contain.
        assert len(protocol.build_upload(blob, base)) == 154


def test_an_oversized_height_cannot_reach_the_gif_slot():
    """--height 960 was the concrete case: 614411 bytes, whose final chunk
    length (11) is a solved CRC_INIT entry, so every packet of it built and
    acked while overwriting the start of the GIF slot."""
    blob = protocol.build_image_file(
        b"\x00" * (protocol.PANEL_WIDTH * 960 * 3), protocol.PANEL_WIDTH, 960)
    end = protocol.PHOTO_FRAME_FLASH_BASE + len(blob)
    assert end > protocol.GIF_FLASH_BASE, "the case under test must actually overrun"
    with pytest.raises(ValueError):
        protocol.build_upload(blob, protocol.PHOTO_FRAME_FLASH_BASE)


def test_force_sends_an_oversized_upload_anyway():
    # The escape hatch --force-size/--force-address rely on; this is a
    # reverse-engineering tool and writing outside a known slot is a
    # legitimate experiment, as long as it is asked for.
    blob = b"\x00" * (protocol.SLOT_CAPACITY[protocol.PHOTO_FRAME_FLASH_BASE] + 2048)
    assert protocol.build_upload(blob, protocol.PHOTO_FRAME_FLASH_BASE, force=True)


def test_an_unknown_address_has_no_capacity_to_check_against():
    # No entry means no model of where the slot ends; inventing one would be
    # worse than passing it through, which is what --force-address is for.
    protocol.check_upload_fits(10_000_000, 0x0DEADBEE)


def test_the_gif_slot_is_capped_at_the_vendor_ceiling():
    assert (protocol.SLOT_CAPACITY[protocol.GIF_FLASH_BASE]
            == protocol.VENDOR_MAX_GIF_BLOB_BYTES)
    with pytest.raises(ValueError):
        protocol.build_upload(b"\x00" * (protocol.VENDOR_MAX_GIF_BLOB_BYTES + 1),
                              protocol.GIF_FLASH_BASE)


def test_the_two_measurable_slots_match_the_firmware_table_stride():
    """The firmware's partition list (re_notes/flash_slot_table.md) is six
    bases on a uniform 0x60000 stride. For the two slots whose size can also
    be got by subtracting adjacent bases, the two methods agree -- which is
    what makes the table trustworthy where it can be checked."""
    assert protocol.SLOT_STRIDE == 0x60000
    for base in (protocol.BACKGROUND_FLASH_BASE, protocol.PHOTO_FRAME_FLASH_BASE):
        assert protocol.SLOT_CAPACITY[base] == protocol.SLOT_STRIDE


def test_the_gif_slot_is_not_assumed_to_be_one_stride():
    """Regression test for a wrong turn worth not repeating. GIF is the last
    table entry, so the stride cannot be checked by subtraction there, and
    assuming it continued gave a 393216-byte cap. The vendor ships 200- and
    214-frame 320x480 animations, which need multiple MB at any per-frame
    rate the captures show (save_to_gif_1: 105131 bytes/frame for real photo
    content), so that cap would refuse the vendor's own assets."""
    assert protocol.SLOT_CAPACITY[protocol.GIF_FLASH_BASE] > protocol.SLOT_STRIDE

    largest_vendor_asset_frames = 214
    real_content_bytes_per_frame = 105131
    protocol.check_upload_fits(
        largest_vendor_asset_frames * real_content_bytes_per_frame // 2,
        protocol.GIF_FLASH_BASE)


def test_the_observed_maximum_is_not_used_as_a_bound():
    """Every capture is 2-3 frames, so the largest one describes the sample,
    not the hardware. Conflating the two is what produced the bad cap."""
    assert (protocol.VENDOR_OBSERVED_MAX_GIF_BLOB_BYTES
            < protocol.SLOT_CAPACITY[protocol.GIF_FLASH_BASE])
    protocol.check_upload_fits(protocol.VENDOR_OBSERVED_MAX_GIF_BLOB_BYTES * 4,
                               protocol.GIF_FLASH_BASE)
