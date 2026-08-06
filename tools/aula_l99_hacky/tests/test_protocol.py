from datetime import datetime

import pytest

import protocol

# The RTC block exactly as save_to_gif_16.pcapng captured it, from the vendor
# app on real hardware at 2026-08-01 05:14:50 (a Saturday). This is the anchor
# for every offset in the block: if the field assignments in
# re_notes/system_monitor_block.md are right, feeding those values back in has
# to reproduce these bytes byte-for-byte.
CAPTURED_BLOCK = bytes.fromhex(
    "00015a1a0801050e3200060000062c0628"
    "1a2219005f" + "00" * 40 + "aa55"
)
CAPTURED_WHEN = datetime(2026, 8, 1, 5, 14, 50)
CAPTURED_MONITOR = protocol.MonitorData(
    cpu_load=6, cpu_temp=44, gpu_load=6, gpu_temp=40,
    air_temp=26, day_high=34, night_low=25, condition=0, humidity=95,
)


def test_captured_block_reproduced_exactly():
    assert len(CAPTURED_BLOCK) == protocol.PACKET_SIZE
    blocks = protocol.build_rtc_blocks(CAPTURED_WHEN, CAPTURED_MONITOR)
    assert blocks == [CAPTURED_BLOCK]


def test_clock_fields_match_the_capture():
    """Guards the offsets individually, so a failure says which field moved."""
    block = protocol.build_rtc_blocks(CAPTURED_WHEN, CAPTURED_MONITOR)[0]
    assert block[protocol.RTC_OFF_TAG] == protocol.RTC_TAG
    assert block[protocol.RTC_OFF_YEAR] == 26
    assert block[protocol.RTC_OFF_MONTH] == 8
    assert block[protocol.RTC_OFF_DAY] == 1
    assert block[protocol.RTC_OFF_HOUR] == 5
    assert block[protocol.RTC_OFF_MINUTE] == 14
    assert block[protocol.RTC_OFF_SECOND] == 50
    assert block[protocol.RTC_OFF_WEEKDAY] == 6  # 2026-08-01 was a Saturday


def test_monitor_fields_match_the_capture():
    block = protocol.build_rtc_blocks(CAPTURED_WHEN, CAPTURED_MONITOR)[0]
    assert block[protocol.RTC_OFF_CPU_LOAD] == 6
    assert block[protocol.RTC_OFF_CPU_TEMP] == 44
    assert block[protocol.RTC_OFF_GPU_LOAD] == 6
    assert block[protocol.RTC_OFF_GPU_TEMP] == 40
    assert block[protocol.RTC_OFF_AIR_TEMP] == 26
    assert block[protocol.RTC_OFF_DAY_HIGH] == 34
    assert block[protocol.RTC_OFF_NIGHT_LOW] == 25
    assert block[protocol.RTC_OFF_CONDITION] == 0
    assert block[protocol.RTC_OFF_HUMIDITY] == 95


def test_no_monitor_data_leaves_the_fields_zero():
    """The GUI and a bare --rtc both go through this path; it has to keep
    emitting the clock-only block that earlier captures confirmed."""
    block = protocol.build_rtc_blocks(CAPTURED_WHEN)[0]
    assert block[13:22] == bytes(9)
    assert block == protocol.build_rtc_blocks(CAPTURED_WHEN, protocol.MonitorData())[0]
    # Clock and framing survive regardless.
    assert block[protocol.RTC_OFF_TAG] == protocol.RTC_TAG
    assert block[protocol.RTC_OFF_SECOND] == 50
    assert block[protocol.TRAILER_OFFSET:] == protocol.TRAILER


def test_view_defaults_to_one_and_lands_at_byte_one():
    assert protocol.build_rtc_blocks(CAPTURED_WHEN)[0][protocol.RTC_OFF_VIEW] == 1
    block = protocol.build_rtc_blocks(CAPTURED_WHEN, view=3)[0]
    assert block[protocol.RTC_OFF_VIEW] == 3


def test_negative_values_encode_as_twos_complement():
    block = protocol.build_rtc_blocks(
        CAPTURED_WHEN, protocol.MonitorData(air_temp=-5, night_low=-128))[0]
    assert block[protocol.RTC_OFF_AIR_TEMP] == 0xFB
    assert block[protocol.RTC_OFF_NIGHT_LOW] == 0x80


@pytest.mark.parametrize("value", [256, -129])
def test_out_of_range_monitor_value_rejected(value):
    with pytest.raises(ValueError):
        protocol.MonitorData(cpu_temp=value)


def test_out_of_range_view_rejected():
    with pytest.raises(ValueError):
        protocol.build_rtc_blocks(CAPTURED_WHEN, view=256)


def test_is_empty_distinguishes_a_clock_only_write():
    assert protocol.MonitorData().is_empty
    assert not protocol.MonitorData(humidity=1).is_empty


def test_parse_condition_accepts_names_and_numbers():
    assert protocol.parse_condition("rain") == 4
    assert protocol.parse_condition("HEAVY-SNOW") == 5
    assert protocol.parse_condition("2") == 2
    assert protocol.parse_condition("0x3") == 3
    with pytest.raises(ValueError):
        protocol.parse_condition("drizzle")


def test_rtc_transfer_wraps_the_block_in_a_session():
    transactions = protocol.build_rtc_transfer(CAPTURED_WHEN, CAPTURED_MONITOR)
    assert [tx.name for tx in transactions] == [
        "begin", "rtc", "rtc-block0", "commit", "end"]
    assert transactions[1].outgoing[:2] == bytes([protocol.CMD_PREFIX, protocol.OP_RTC])
    assert transactions[1].outgoing[8] == 1  # one data block follows
    assert transactions[2].outgoing == CAPTURED_BLOCK


# Four audio spectrum blocks exactly as save_to_gif_17.pcapng captured them,
# chosen to pin the band ordering rather than just the framing: the first is
# the opening frame (energy only in the low bands), the last is a late frame
# with the low bands silent and the high ones loud. If the levels were
# reversed, or offset by one, or the block were three bytes shorter, at least
# one of these would stop reproducing.
CAPTURED_AUDIO = {
    # packet 42, the first frame in the capture
    "opening": (
        "040864191e0c0401" + "00" * 56,
        [25, 30, 12, 4, 1] + [0] * 18,
    ),
    # packet 200, energy at both ends of the spectrum at once
    "split": (
        "04086430381404000000000000000003000000000004030e0b28" + "00" * 38,
        [48, 56, 20, 4, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 4, 3, 14, 11, 40],
    ),
    # packet 1732, the broadest frame in the capture
    "broad": (
        "0408641e211808030303030b0c0b01011001" + "00" * 46,
        [30, 33, 24, 8, 3, 3, 3, 3, 11, 12, 11, 1, 1, 16, 1] + [0] * 8,
    ),
    # packet 1770, the low bands silent -- the frame that fixes the direction
    "high-only": (
        "0408640000000000000000081b202018210b03" + "00" * 45,
        [0] * 8 + [8, 27, 32, 32, 24, 33, 11, 3] + [0] * 7,
    ),
}


@pytest.mark.parametrize("name", sorted(CAPTURED_AUDIO))
def test_captured_audio_block_reproduced_exactly(name):
    expected_hex, levels = CAPTURED_AUDIO[name]
    expected = bytes.fromhex(expected_hex)
    assert len(expected) == protocol.PACKET_SIZE
    assert len(levels) == protocol.AUDIO_BAND_COUNT
    assert protocol.build_audio_blocks(levels) == [expected]


@pytest.mark.parametrize("name", sorted(CAPTURED_AUDIO))
def test_captured_audio_block_round_trips(name):
    expected_hex, levels = CAPTURED_AUDIO[name]
    parsed, scale = protocol.parse_audio_block(bytes.fromhex(expected_hex))
    assert parsed == levels
    assert scale == protocol.AUDIO_SCALE_DEFAULT


def test_audio_header_bytes_are_where_the_capture_put_them():
    block = protocol.build_audio_blocks([1])[0]
    assert block[protocol.AUDIO_OFF_RHYTHM] == protocol.AUDIO_RHYTHM_DEFAULT
    assert block[protocol.AUDIO_OFF_BACKGROUND_MODE] == (
        protocol.AUDIO_BACKGROUND_MODE_DEFAULT)
    assert block[protocol.AUDIO_OFF_SCALE] == protocol.AUDIO_SCALE_DEFAULT
    assert block[protocol.AUDIO_OFF_LEVELS] == 1


def test_audio_background_brightness_lands_in_the_tail():
    """The background-brightness byte is a best-guess mapping into the first
    never-written tail byte -- the Music Rhythm tab's Background Brightness
    slider (see re_notes/audio_spectrum_block.md). It defaults to zero, which
    is what every captured frame's tail held."""
    block = protocol.build_audio_blocks([1])[0]
    assert block[protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS] == (
        protocol.AUDIO_BACKGROUND_BRIGHTNESS_DEFAULT)
    nondefault = protocol.build_audio_blocks([1], background_brightness=0x55)[0]
    assert nondefault[protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS] == 0x55
    # ...and nothing else in the tail moves.
    assert (block[protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS + 1:] ==
            nondefault[protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS + 1:])


def test_audio_music_settings_ride_the_header_bytes():
    """Rhythm -> byte 0, Amplitude -> byte 2, Background Mode -> byte 1. The
    first two are corroborated by the single capture's default values; the
    rhythm/background placement was swapped from the original guess after a
    hardware check (the Rhythm dropdown moves the panel's background)."""
    block = protocol.build_audio_blocks(
        [1], scale=55, rhythm=9, background_mode=3, background_brightness=7)[0]
    assert block[protocol.AUDIO_OFF_SCALE] == 55
    assert block[protocol.AUDIO_OFF_RHYTHM] == 9
    assert block[protocol.AUDIO_OFF_BACKGROUND_MODE] == 3
    assert block[protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS] == 7


def test_audio_rhythm_and_background_lists_match_the_vendor():
    """Both dropdowns are populated from the same 15-entry range (strings
    106..120) in the original software, and the byte an entry sends is its
    index. Off leads the list: a hardware check (background byte 0x00 vs 0x0B
    on the panel) showed byte 0 is the no-background state, so Off = 0, with
    every other entry shifted up by one from the original guess."""
    assert len(protocol.AUDIO_RHYTHM_NAMES) == 15
    assert protocol.AUDIO_RHYTHM_NAMES == protocol.AUDIO_BACKGROUND_MODE_NAMES
    assert protocol.AUDIO_RHYTHM_NAMES.index("Off") == 0
    assert protocol.AUDIO_RHYTHM_NAMES.index("Green/Yellow/Red") == 1
    assert protocol.AUDIO_RHYTHM_NAMES.index("Spectrum Cycle") == 5
    assert "Ambilight" in protocol.AUDIO_RHYTHM_NAMES
    assert protocol.AUDIO_RHYTHM_DEFAULT == 0x04
    assert protocol.AUDIO_BACKGROUND_MODE_DEFAULT == 0x08


def test_audio_block_has_no_trailer():
    """Every other outbound block in this protocol ends AA 55; this one does
    not, in all 137 captured frames. Adding one would be the natural 'fix'."""
    block = protocol.build_audio_blocks([100] * protocol.AUDIO_BAND_COUNT)[0]
    assert block[protocol.TRAILER_OFFSET:] != protocol.TRAILER
    tail_from = protocol.AUDIO_OFF_LEVELS + protocol.AUDIO_BAND_COUNT
    assert block[tail_from:] == bytes(protocol.PACKET_SIZE - tail_from)


def test_short_level_list_is_padded_with_silence():
    """Driving one band and leaving the rest silent is how the bar-to-band
    mapping gets confirmed on hardware, so it has to be a legal frame."""
    assert protocol.build_audio_blocks([42]) == protocol.build_audio_blocks(
        [42] + [0] * (protocol.AUDIO_BAND_COUNT - 1))


def test_too_many_bands_rejected():
    with pytest.raises(ValueError):
        protocol.build_audio_blocks([0] * (protocol.AUDIO_BAND_COUNT + 1))


def test_level_above_the_scale_byte_rejected():
    with pytest.raises(ValueError):
        protocol.build_audio_blocks([101])
    # ...but the same level is fine once the scale says it can be.
    assert protocol.build_audio_blocks([101], scale=200)[0][3] == 101


def test_every_captured_level_fits_the_vendors_quantum():
    """The vendor's levels are all floor(n * 8 / 5). Not enforced by the
    builder, but if this ever fails the reading in the notes is wrong."""
    numerator, denominator = protocol.AUDIO_LEVEL_QUANTUM
    allowed = {n * numerator // denominator for n in range(256)}
    for _, levels in CAPTURED_AUDIO.values():
        assert set(levels) <= allowed


def test_parse_audio_levels_accepts_commas_and_spaces():
    assert protocol.parse_audio_levels("100,80,60") == [100, 80, 60]
    assert protocol.parse_audio_levels("0 0 0 100") == [0, 0, 0, 100]
    assert protocol.parse_audio_levels("100") == [100]
    assert protocol.parse_audio_levels("0x64") == [100]
    with pytest.raises(ValueError):
        protocol.parse_audio_levels("100,loud")
    with pytest.raises(ValueError):
        protocol.parse_audio_levels("  ")


def test_audio_frame_is_commit_then_command_then_block():
    transactions = protocol.build_audio_frame([1, 2, 3])
    assert [tx.name for tx in transactions] == ["commit", "audio", "audio-block0"]
    assert transactions[1].outgoing[:2] == bytes([protocol.CMD_PREFIX, protocol.OP_AUDIO])
    assert transactions[1].outgoing[8] == 1  # one data block follows
    assert transactions[2].outgoing == protocol.build_audio_blocks([1, 2, 3])[0]
    # No session framing on this path at all, unlike build_transfer().
    assert not any(tx.name in ("begin", "end") for tx in transactions)


def test_dongle_packet_without_monitor_data_is_the_prior_art_layout():
    packet = protocol.build_dongle_rtc_packet(CAPTURED_WHEN)
    assert len(packet) == protocol.DONGLE_PACKET_SIZE
    assert packet[4:6] == bytes([0x01, protocol.RTC_TAG])
    assert packet[6:12] == bytes([26, 8, 1, 5, 14, 50])
    assert packet[17:19] == protocol.TRAILER
    assert packet[-1] == protocol.checksum(packet[:-1])


def test_dongle_packet_with_monitor_data_uses_the_shifted_layout():
    packet = protocol.build_dongle_rtc_packet(CAPTURED_WHEN, CAPTURED_MONITOR)
    assert len(packet) == protocol.DONGLE_PACKET_SIZE
    shift = protocol.RTC_DONGLE_SHIFT
    assert packet[protocol.RTC_OFF_TAG + shift] == protocol.RTC_TAG
    assert packet[protocol.RTC_OFF_YEAR + shift] == 26
    assert packet[protocol.RTC_OFF_CPU_LOAD + shift] == 6
    assert packet[protocol.RTC_OFF_HUMIDITY + shift] == 95
    trailer_at = protocol.RTC_OFF_HUMIDITY + shift + 1
    assert packet[trailer_at:trailer_at + 2] == protocol.TRAILER
    assert packet[-1] == protocol.checksum(packet[:-1])


# One realtime-stream frame exactly as save_to_gif_18.pcapng captured it: the
# 8 data blocks of opcode 0x20, concatenated. Everything the vendor app sent is
# here -- the packed key order, the 83 unlit keys transmitted as black, the
# zero padding past slot 84, and the absence of any AA 55 trailer. Only the
# Pause key (0x73) is lit, at #050026.
CAPTURED_STREAM_PAYLOAD = bytes.fromhex(
    "0100000002000000030000000400000005000000060000000700000008000000"
    "090000000a0000000b0000000c0000000d000000770000007000000071000000"
    "7305002613000000140000001500000016000000170000001800000019000000"
    "1a0000001b0000001c0000001d0000001e0000001f0000006700000075000000"
    "25000000260000002700000028000000290000002a0000002b0000002c000000"
    "2d0000002e0000002f0000003000000031000000430000007600000037000000"
    "38000000390000003a0000003b0000003c0000003d0000003e0000003f000000"
    "4000000041000000420000005500000079000000490000004a0000004b000000"
    "4c0000004d0000004e0000004f00000050000000510000005200000053000000"
    "5400000065000000780000005b0000005c0000005d0000005e00000060000000"
    "6200000063000000640000006600000000000000000000000000000000000000"
    + "00" * 160
)
CAPTURED_STREAM_COLORS = {0x73: (0x05, 0x00, 0x26)}


def test_captured_stream_frame_reproduced_exactly():
    blocks = protocol.build_stream_blocks(CAPTURED_STREAM_COLORS)
    assert len(blocks) == protocol.STREAM_BLOCK_COUNT
    assert all(len(block) == protocol.PACKET_SIZE for block in blocks)
    assert b"".join(blocks) == CAPTURED_STREAM_PAYLOAD


def test_stream_frame_carries_no_trailer():
    """The one structural difference most likely to get 'fixed' by mistake."""
    blocks = protocol.build_stream_blocks(CAPTURED_STREAM_COLORS)
    assert not any(protocol.TRAILER in block for block in blocks)


def test_stream_key_order_is_the_same_keys_as_the_matrix_layout():
    assert len(protocol.STREAM_KEY_ORDER) == protocol.STREAM_KEY_COUNT
    assert set(protocol.STREAM_KEY_ORDER) == set(protocol.KEY_IDS)
    assert len(set(protocol.STREAM_KEY_ORDER)) == len(protocol.STREAM_KEY_ORDER)
    # ...but not in the same order, which is the whole point of the constant.
    assert protocol.STREAM_KEY_ORDER != protocol.KEY_IDS


def test_unlit_keys_are_still_transmitted_with_their_id():
    """Omitting a key from `colors` must not omit its slot -- that would shift
    every key after it."""
    blocks = protocol.build_stream_blocks({})
    payload = b"".join(blocks)
    for slot, key_id in enumerate(protocol.STREAM_KEY_ORDER):
        offset = slot * protocol.BYTES_PER_KEY
        assert payload[offset] == key_id
        assert payload[offset + 1:offset + 4] == b"\x00\x00\x00"


def test_padding_past_the_physical_keys_is_fully_zero():
    payload = b"".join(protocol.build_stream_blocks(protocol.build_uniform_colors((1, 2, 3))))
    padding_at = protocol.STREAM_KEY_COUNT * protocol.BYTES_PER_KEY
    assert payload[padding_at:] == bytes(
        (protocol.STREAM_SLOT_COUNT - protocol.STREAM_KEY_COUNT) * protocol.BYTES_PER_KEY)


def test_parse_stream_blocks_round_trips_the_capture():
    blocks = [CAPTURED_STREAM_PAYLOAD[i:i + protocol.PACKET_SIZE]
              for i in range(0, len(CAPTURED_STREAM_PAYLOAD), protocol.PACKET_SIZE)]
    colors = protocol.parse_stream_blocks(blocks)
    assert colors[0x73] == (0x05, 0x00, 0x26)
    assert set(colors) == set(protocol.KEY_IDS)
    assert all(rgb == (0, 0, 0) for key_id, rgb in colors.items() if key_id != 0x73)


def test_parse_stream_blocks_rejects_a_frame_in_a_different_order():
    scrambled = bytearray(CAPTURED_STREAM_PAYLOAD)
    scrambled[0] = 0x02  # slot 0 should hold key 0x01
    blocks = [bytes(scrambled[i:i + protocol.PACKET_SIZE])
              for i in range(0, len(scrambled), protocol.PACKET_SIZE)]
    with pytest.raises(ValueError):
        protocol.parse_stream_blocks(blocks)


def test_stream_frame_has_no_session_framing_and_commits_last():
    transactions = protocol.build_stream_frame(CAPTURED_STREAM_COLORS)
    assert [tx.name for tx in transactions] == (
        ["stream"] + [f"stream-block{i}" for i in range(8)] + ["commit"])
    assert transactions[0].outgoing[:2] == bytes(
        [protocol.CMD_PREFIX, protocol.OP_COLOR_STREAM])
    assert transactions[0].outgoing[8] == protocol.STREAM_BLOCK_COUNT
    assert transactions[1].outgoing == CAPTURED_STREAM_PAYLOAD[:protocol.PACKET_SIZE]


def test_dongle_session_init_reply_is_the_l99_dongles_own_bytes():
    # Read back from the real L99 dongle (05AC:024F) with the keyboard paired
    # and unpaired: identical every time, byte 11 = 0x29 (0x08 on the F75).
    reply = protocol.SESSION_INIT_IN
    assert len(reply) == protocol.DONGLE_PACKET_SIZE
    assert reply[protocol.SESSION_INIT_VERSION_BYTE] == 0x29
    assert reply[-1] == protocol.checksum(reply[:-1])
    assert reply[:7] == bytes.fromhex("02000040300000")
    assert reply[7:11] == bytes.fromhex("450c0a80")


def test_dongle_replies_match_tolerates_the_version_byte():
    assert protocol.dongle_replies_match(protocol.SESSION_INIT_IN, protocol.SESSION_INIT_IN)
    f75_prior_art = bytes.fromhex(
        "02000040300000450c0a800801ffff0000000000000000000000000000000054"
    )
    assert protocol.dongle_replies_match(protocol.SESSION_INIT_IN, f75_prior_art)
    other = bytearray(protocol.SESSION_INIT_IN)
    other[3] = 0x00  # not the version byte: must not match
    assert not protocol.dongle_replies_match(bytes(other), protocol.SESSION_INIT_IN)
    assert not protocol.dongle_replies_match(
        protocol.SESSION_INIT_IN, bytes.fromhex("00"))


def test_parse_color_blocks_rejects_a_short_block():
    """A short block would otherwise slice to a 2-element "colour" and be
    returned as one, so a caller reading via read_report() (which returns
    whatever arrived) would get wrong colours rather than an error."""
    blocks = [bytes(protocol.PACKET_SIZE)] * (protocol.COLOR_BLOCK_COUNT - 1)
    blocks.append(bytes(protocol.PACKET_SIZE - 1))
    with pytest.raises(ValueError, match="block"):
        protocol.parse_color_blocks(blocks)


def test_parse_color_blocks_round_trips_a_full_read():
    colors = protocol.build_uniform_colors((10, 20, 30))
    # A query reply has no terminator block, unlike a write -- see
    # build_color_query_commands.
    blocks = protocol.build_color_blocks(colors)[:-1]
    assert protocol.parse_color_blocks(blocks) == colors
