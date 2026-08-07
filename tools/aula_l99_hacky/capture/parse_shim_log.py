"""Capture log parser for the LD_PRELOAD shim (see wine_ioctl_shim.c).

Line formats, one event per line:

    I  <ns> <pid> <tid> <fd> <dev> <req> <dir> <size> <hex> <ret> <errno>
    RW <ns> <pid> <tid> <fd> <dev> <dir> <size> <hex> <ret> <errno>

`I` lines are hidraw ioctls: `dir` is OUT (HIDIOCSFEATURE, the payload the
host sends), IN (HIDIOCGFEATURE, the payload the device replied) or META
(no payload). `RW` lines are read/write on /dev/hidraw or /dev/ttyACM.

The vendor app's steady-state colour poll -- commit -> query -> 9 IN blocks,
repeated -- dominates a capture and is stripped by default; the remaining
events are the isolated setting change. `--verify` re-checks captured
sessions byte-for-byte against this package's protocol builders.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aula_l99_hacky import protocol

IOCTL_RE = re.compile(
    r"^I (\d+) (\d+) (\d+) (\d+) (\S+) ([0-9a-fA-F]+) (OUT|IN|META) (\d+) ([0-9a-fA-F ]*) (-?\d+) (-?\d+)$"
)
RW_RE = re.compile(
    r"^RW (\d+) (\d+) (\d+) (\d+) (\S+) (read|write) (\d+) ([0-9a-fA-F ]*) (-?\d+) (-?\d+)$"
)

OPCODE_NAMES = {
    value: name.removeprefix("OP_").lower()
    for name, value in vars(protocol).items()
    if name.startswith("OP_") and isinstance(value, int)
}
OPCODE_NAMES[protocol.EFFECT_CUSTOM] = "custom"

POLL_QUERY_BLOCKS = protocol.COLOR_BLOCK_COUNT


@dataclass
class Event:
    ns: int
    pid: int
    tid: int
    fd: int
    dev: str
    req: int | None
    direction: str
    data: bytes
    ret: int
    errno: int
    kind: str = "ioctl"

    @property
    def is_command(self) -> bool:
        return (
            self.kind == "ioctl"
            and self.direction == "OUT"
            and len(self.data) > 1
            and self.data[0] == protocol.CMD_PREFIX
        )

    @property
    def opcode(self) -> int:
        return self.data[1] if self.is_command else -1


def parse_hex(value: str) -> bytes:
    cleaned = value.strip()
    return bytes.fromhex(cleaned) if cleaned else b""


def parse_log(path: str) -> list[Event]:
    events = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            match = IOCTL_RE.match(line)
            if match:
                ns, pid, tid, fd, dev, req, direction, size, hexed, ret, err = match.groups()
                data = parse_hex(hexed)
                if len(data) == protocol.PACKET_SIZE + 1 and data[0] == protocol.REPORT_ID:
                    data = data[1:]
                events.append(
                    Event(int(ns), int(pid), int(tid), int(fd), dev, int(req, 16),
                          direction, data, int(ret), int(err))
                )
                continue
            match = RW_RE.match(line)
            if match:
                ns, pid, tid, fd, dev, direction, size, hexed, ret, err = match.groups()
                events.append(
                    Event(int(ns), int(pid), int(tid), int(fd), dev, None,
                          direction, parse_hex(hexed), int(ret), int(err),
                          kind="rw")
                )
    return events


def drop_poll_loop(events: list[Event]) -> list[Event]:
    """Strip the vendor app's steady-state colour poll.

    The loop is commit (0x02 out) -> query (0xF5 out) -> 9 IN blocks,
    repeated with nothing in between. Runs of two or more consecutive
    identical cycles are removed wholesale.
    """
    out = list(events)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(out):
            cycles = 0
            j = i
            while True:
                if j >= len(out):
                    break
                if not out[j].is_command or out[j].opcode != protocol.OP_COMMIT:
                    break
                if j + 1 >= len(out):
                    break
                if not out[j + 1].is_command or out[j + 1].opcode != protocol.OP_COLOR_QUERY:
                    break
                blocks = out[j + 2:j + 2 + POLL_QUERY_BLOCKS]
                if len(blocks) != POLL_QUERY_BLOCKS:
                    break
                if any(b.kind != "ioctl" or b.direction != "IN" for b in blocks):
                    break
                cycles += 1
                j += 2 + POLL_QUERY_BLOCKS
            if cycles >= 2:
                del out[i:i + (2 + POLL_QUERY_BLOCKS) * cycles]
                changed = True
                continue
            i += 1
    return out


def filter_events(events: list[Event], dev: str | None, directions: list[str] | None) -> list[Event]:
    result = []
    for event in events:
        if dev and dev not in event.dev:
            continue
        if event.kind == "rw":
            if directions and event.direction not in directions:
                continue
        elif directions and event.direction not in directions:
            continue
        result.append(event)
    return result


def describe(event: Event) -> str:
    if event.kind == "rw":
        label = f"{event.direction}"
    elif event.direction == "META":
        label = "meta"
    elif event.is_command:
        label = OPCODE_NAMES.get(event.opcode, f"op{event.opcode:02x}")
    else:
        label = "data"
    return label


def format_event(index: int, event: Event) -> str:
    direction = event.direction if event.kind == "ioctl" else ""
    prefix = f"{index:3} {direction:<4} {describe(event):<12} {len(event.data):>2}B "
    if event.kind == "rw":
        return prefix + f"dev={event.dev} {event.data.hex(' ')[:140]}"
    return prefix + f"req=0x{event.req:08x} dev={event.dev} {event.data.hex(' ')[:140]}"


def diff_index(expected: bytes, actual: bytes) -> int:
    for index in range(max(len(expected), len(actual))):
        left = expected[index] if index < len(expected) else -1
        right = actual[index] if index < len(actual) else -1
        if left != right:
            return index
    return -1


def check_packet(name: str, expected: bytes, actual: bytes, checks: list) -> None:
    if expected == actual:
        checks.append((True, f"ok {name}"))
    else:
        at = diff_index(expected, actual)
        checks.append(
            (False, f"mismatch {name} at byte {at}: expected 0x{expected[at]:02x}, "
                    f"got 0x{actual[at]:02x}")
        )


def check_blocks(opcode: int, blocks: list[bytes], checks: list) -> None:
    if opcode == protocol.OP_COLOR_SET:
        try:
            rebuilt = protocol.build_color_blocks(protocol.parse_color_blocks(blocks))
        except ValueError as exc:
            checks.append((False, f"color blocks unparseable: {exc}"))
            return
        for index, (original, expect) in enumerate(zip(blocks, rebuilt)):
            check_packet(f"color block {index}", expect, original, checks)
    elif opcode == protocol.OP_EFFECT:
        for index, block in enumerate(blocks):
            try:
                expect = protocol.build_effect_blocks(
                    block[0], tuple(block[1:4]), block[10], block[9], block[8]
                )[0]
            except ValueError as exc:
                checks.append((False, f"effect block {index} outside builder range: {exc}"))
                continue
            check_packet(f"effect block {index}", expect, block, checks)
    elif opcode == protocol.OP_RTC:
        for index, block in enumerate(blocks):
            when = datetime(2000 + block[protocol.RTC_OFF_YEAR],
                            block[protocol.RTC_OFF_MONTH],
                            block[protocol.RTC_OFF_DAY],
                            block[protocol.RTC_OFF_HOUR],
                            block[protocol.RTC_OFF_MINUTE],
                            block[protocol.RTC_OFF_SECOND])
            monitor = protocol.MonitorData(
                cpu_load=block[protocol.RTC_OFF_CPU_LOAD],
                cpu_temp=block[protocol.RTC_OFF_CPU_TEMP],
                gpu_load=block[protocol.RTC_OFF_GPU_LOAD],
                gpu_temp=block[protocol.RTC_OFF_GPU_TEMP],
                air_temp=block[protocol.RTC_OFF_AIR_TEMP],
                day_high=block[protocol.RTC_OFF_DAY_HIGH],
                night_low=block[protocol.RTC_OFF_NIGHT_LOW],
                condition=block[protocol.RTC_OFF_CONDITION],
                humidity=block[protocol.RTC_OFF_HUMIDITY],
            )
            expect = protocol.build_rtc_blocks(when, monitor, block[protocol.RTC_OFF_VIEW])[0]
            check_packet(f"rtc block {index}", expect, block, checks)
    elif opcode == protocol.OP_SETTINGS_WRITE:
        for index, block in enumerate(blocks):
            rebuilt = bytearray(protocol.PACKET_SIZE)
            rebuilt[protocol.SETTINGS_OFF_TAG0] = 0x00
            rebuilt[protocol.SETTINGS_OFF_TAG1] = 0x01
            rebuilt[protocol.SETTINGS_OFF_RESPONSE] = block[protocol.SETTINGS_OFF_RESPONSE]
            rebuilt[protocol.SETTINGS_OFF_SLEEP] = block[protocol.SETTINGS_OFF_SLEEP]
            rebuilt[protocol.TRAILER_OFFSET:protocol.TRAILER_OFFSET + 2] = protocol.TRAILER
            check_packet(f"settings block {index}", bytes(rebuilt), block, checks)
    elif opcode == protocol.OP_COLOR_STREAM:
        try:
            rebuilt = protocol.build_stream_blocks(protocol.parse_stream_blocks(blocks))
        except ValueError as exc:
            checks.append((False, f"stream frames unparseable: {exc}"))
            return
        for index, (original, expect) in enumerate(zip(blocks, rebuilt)):
            check_packet(f"stream block {index}", expect, original, checks)
    elif opcode == protocol.OP_AUDIO:
        for index, block in enumerate(blocks):
            try:
                levels, scale = protocol.parse_audio_block(block)
                expect = protocol.build_audio_blocks(
                    levels, scale, block[0], block[1], block[26]
                )[0]
            except ValueError as exc:
                checks.append((False, f"audio frame {index} unparseable: {exc}"))
                continue
            check_packet(f"audio frame {index}", expect, block, checks)


def iter_sessions(events: list[Event]) -> list[list[Event]]:
    out = [e for e in drop_poll_loop(events)
           if e.kind == "ioctl" and e.direction == "OUT"]
    sessions = []
    current = None
    for event in out:
        if event.is_command and event.opcode == protocol.OP_BEGIN:
            if current is not None:
                sessions.append(current)
            current = []
        if current is not None:
            current.append(event)
        if event.is_command and event.opcode == protocol.OP_END:
            sessions.append(current)
            current = None
    if current is not None:
        sessions.append(current)
    return sessions


def verify_sessions(events: list[Event]) -> list[tuple[str, list]]:
    results = []
    for index, session in enumerate(iter_sessions(events), start=1):
        checks: list = []
        i = 0
        while i < len(session):
            event = session[i]
            if event.opcode == protocol.OP_BEGIN:
                check_packet("begin", protocol.build_command(protocol.OP_BEGIN), event.data, checks)
                i += 1
            elif event.opcode == protocol.OP_COMMIT:
                check_packet("commit", protocol.build_command(protocol.OP_COMMIT), event.data, checks)
                i += 1
            elif event.opcode == protocol.OP_END:
                check_packet("end", protocol.build_command(protocol.OP_END), event.data, checks)
                i += 1
            elif event.is_command:
                block_count = event.data[8]
                byte2 = 1 if event.opcode == protocol.OP_SETTINGS_WRITE else 0
                expect = protocol.build_command(event.opcode, block_count, byte2)
                name = OPCODE_NAMES.get(event.opcode, f"op{event.opcode:02x}")
                check_packet(f"cmd {name}", expect, event.data, checks)
                blocks = [x.data for x in session[i + 1:i + 1 + block_count]]
                if len(blocks) != block_count:
                    checks.append(
                        (False, f"cmd {name}: expected {block_count} data blocks, "
                                f"saw {len(blocks)}")
                    )
                else:
                    check_blocks(event.opcode, blocks, checks)
                    if event.opcode == protocol.OP_COLOR_STREAM:
                        pass
                i += 1 + block_count
            else:
                checks.append((False, f"unexpected {describe(event)} outside session framing"))
                i += 1
        results.append((f"session {index}", checks))
    return results


SETTINGS_TAG_BYTES = (protocol.SETTINGS_OFF_TAG0, protocol.SETTINGS_OFF_TAG1)
SETTINGS_RESPONSE_OFFSET = protocol.SETTINGS_OFF_RESPONSE
SETTINGS_SLEEP_OFFSET = protocol.SETTINGS_OFF_SLEEP


def summarize_settings(events: list[Event]) -> list[dict]:
    """The 0x17 settings-panel blocks in capture order.

    Per re_notes/settings_write.md the block carries the whole settings panel
    on every write: byte 6 is the sleep-time value (0..3 = no sleep / 1 / 5 /
    30 minutes) and byte 8 the response-time level (1..5, delays in
    protocol.RESPONSE_TIME_DELAYS_MS).
    """
    rounds: list[dict] = []
    for session in iter_sessions(events):
        for index, event in enumerate(session):
            if not (event.is_command and event.opcode == protocol.OP_SETTINGS_WRITE):
                continue
            block_count = event.data[8]
            blocks = [x.data for x in session[index + 1:index + 1 + block_count]]
            if len(blocks) != block_count:
                rounds.append({"ts": event.ns,
                               "error": f"expected {block_count} blocks, saw {len(blocks)}"})
                continue
            for block in blocks:
                rounds.append({"ts": event.ns, "block": block})
    return rounds


def ordered_unique(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def print_settings(rounds: list[dict]) -> int:
    if not rounds:
        print("no 0x17 settings-panel rounds found")
        return 1
    base = rounds[0]["ts"]
    print("SETTINGS rounds (opcode 0x17), one row per panel write:")
    print(f"{' #':>3} {'ts':>10} {'byte6':>6} {'byte8':>6} {'changed':>8}  notes")
    byte6_seen: list[int] = []
    byte8_seen: list[int] = []
    for number, round_ in enumerate(rounds, start=1):
        if "error" in round_:
            print(f"{number:>3} {'-':>10} {'-':>6} {'-':>6} {'-':>8}  {round_['error']}")
            continue
        block = round_["block"]
        sleep = block[SETTINGS_SLEEP_OFFSET]
        response = block[SETTINGS_RESPONSE_OFFSET]
        byte6_seen.append(sleep)
        byte8_seen.append(response)
        changed = []
        if number > 1 and "block" in rounds[number - 2]:
            previous = rounds[number - 2]["block"]
            if previous[SETTINGS_SLEEP_OFFSET] != sleep:
                changed.append("sleep")
            if previous[SETTINGS_RESPONSE_OFFSET] != response:
                changed.append("rsp")
        notes = []
        tags = block[SETTINGS_TAG_BYTES[0]:SETTINGS_TAG_BYTES[1] + 1]
        if tags != bytes([0x00, 0x01]):
            notes.append(f"tags {tags.hex(' ')}")
        if block[protocol.TRAILER_OFFSET:protocol.TRAILER_OFFSET + 2] != protocol.TRAILER:
            notes.append("no AA55 trailer")
        unexpected = [i for i, value in enumerate(block)
                      if value and i not in (*SETTINGS_TAG_BYTES,
                                            SETTINGS_RESPONSE_OFFSET,
                                            SETTINGS_SLEEP_OFFSET,
                                            protocol.TRAILER_OFFSET,
                                            protocol.TRAILER_OFFSET + 1)]
        if unexpected:
            shown = ", ".join(f"{i}=0x{block[i]:02x}" for i in unexpected[:8])
            notes.append(f"nonzero elsewhere: {shown}")
        relative = (round_["ts"] - base) / 1e9
        print(f"{number:>3} {relative:>9.3f}s {response:>6} {sleep:>6} "
              f"{','.join(changed) or '-':>8}  {' '.join(notes)}")
    print(f"byte6 (sleep-time, 0..3) values in order:   {ordered_unique(byte6_seen)}")
    print(f"byte8 (response-time, 1..5) values in order: {ordered_unique(byte8_seen)}")
    print("sleep-time meaning: wire value -> minutes via protocol.SLEEP_TIME_MINUTES "
          f"({protocol.SLEEP_TIME_MINUTES})")
    print("response-time meaning: wire level -> per-link ms delays via "
          f"protocol.RESPONSE_TIME_DELAYS_MS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse a capture log from wine_ioctl_shim.so (see "
                    "tools/aula_l99_hacky/README.md for the capture workflow)."
    )
    parser.add_argument("log", nargs="+", help="capture log file(s), in capture order")
    parser.add_argument("--keep-poll", action="store_true",
                        help="keep the steady-state commit/query colour-poll loop")
    parser.add_argument("--dev", metavar="SUBSTR",
                        help="only events whose device path contains SUBSTR")
    parser.add_argument("--dir", choices=("OUT", "IN", "META"), action="append",
                        help="only ioctl events of this direction (repeatable)")
    parser.add_argument("--hex", action="store_true",
                        help="print each payload as bare space-separated hex, one per "
                             "line -- the --send-hex paste format")
    parser.add_argument("--verify", action="store_true",
                        help="check captured sessions byte-for-byte against protocol.py builders")
    parser.add_argument("--settings", action="store_true",
                        help="summarise the 0x17 settings-panel rounds (response-time and "
                             "sleep-time slots) as a per-write table")
    args = parser.parse_args(argv)

    events = []
    for path in args.log:
        events.extend(parse_log(path))

    if args.verify:
        failed = 0
        for label, checks in verify_sessions(events):
            print(f"VERIFY {label}")
            for passed, detail in checks:
                print(f"  [{'PASS' if passed else 'FAIL'}] {detail}")
                failed += 0 if passed else 1
            overall = "PASS" if all(passed for passed, _ in checks) else "FAIL"
            print(f"VERIFY {label}: {overall}")
            if overall == "FAIL":
                failed += 1
        print(f"verify summary: {failed} failing check line(s)")
        return 0 if failed == 0 else 1

    if args.settings:
        return print_settings(summarize_settings(events))

    if not args.keep_poll:
        events = drop_poll_loop(events)
    events = filter_events(events, args.dev, args.dir)

    if args.hex:
        for event in events:
            if event.kind == "rw":
                continue
            if event.data:
                print(event.data.hex(" "))
        return 0

    for index, event in enumerate(events, start=1):
        print(format_event(index, event))
    print(f"{len(events)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
