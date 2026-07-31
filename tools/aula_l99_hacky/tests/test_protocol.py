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
