# Key remapping ("My Exclusive Config") and macros

Decoded from fresh shim captures of the vendor app under Wine, 2026-08-13.
Source logs (all under `capture/logs/`, gitignored):

| Log | Contents |
|---|---|
| `remap_1.log` | app startup with window creation failing: RTC set + `0x11`/`0x27` sync writes (all-zero tables) |
| `remap_1b.log` | app startup with working window, home screen, Custom Key tab opened: no profile traffic at all |
| `remap_2.log` | interactive: Pause disabled then defaulted, Caps Lock disabled, Caps->Esc remap, Caps->macro, Caps->Volume Up |
| `macro_test.log` | app restart, rebind Caps Lock to the macro |
| `macro_save.log` | recording a new macro ("xxyyzz") and saving it |

Hardware verification after each capture: remaps, disables, media bindings and
the macro sequence all survive the app being closed — they live on the
keyboard. Macro playback is on-board: the recorded sequence replays with no
driver running.

The older `wireshark_dumps/profile_read_1.pcapng` (see
`settings_write.md`) mislabeled `0x11`/`0x27` as profile *reads*: the shim
captures show they are feature-report **writes** (`SET_REPORT`, direction OUT),
exactly like `0x23`/`0x17`. Treat that pcapng's "read" naming as a direction
misjudgement from Wireshark's URB view.

## The key-profile table (opcode `0x11`)

Session shape: `BEGIN (0x18)` -> `0x11` with `byte[8]=0x09` -> 9 data blocks ->
`COMMIT (0x02)` -> `END (0xF0)`. The whole table is rewritten on every change
or Apply; it is not incremental. (In one capture two consecutive identical
sessions appeared for a single UI change — touching the panel and then
applying both trigger a write. Treat "one write per panel change/apply" as the
normal case.)

The 9 blocks are 576 bytes: **4-byte entries indexed by `key_index`** from the
vendor's `layouts/rgb-keyboard.xml`, entry at `key_index * 4`. Confirmed with
Pause (`key_index=115` -> offset 460) and Caps Lock (`key_index=55` ->
offset 220). The last block carries `AA 55` at bytes 62-63; the entries
themselves are plain byte fields.

```
entry (4 bytes):  [type] [p1] [p2] [p3]
```

| type | p1 | p2 | p3 | Meaning | Witness |
|---|---|---|---|---|---|
| `0x00` | 0 | 0 | 0 | unchanged / default | every table |
| `0x02` | 0 | HID usage | 0 | remap to key | Caps->Esc: `02 00 29 00` (0x29 = Esc) |
| `0x03` | consumer usage | 0 | 0 | multimedia | Caps->Volume Up: `03 e9 00 00` (0xE9 = Volume Up) |
| `0x05` | `0x03` | 0 | 0 | disable key | Pause & Caps disabled: `05 03 00 00` |
| `0x06` | 0 | 0 | 0 | macro trigger | Caps->macro: `06 00 00 00` |

Unknowns: what `0x05`'s `p1=0x03` means (a sub-type, or the low byte of a
16-bit type `0x0305`); the type codes for the app's remaining key types
(custom function with mouse/media/windows-shortcut/open-program/send-text/
multi-key; Fn-layer entries), which all still await captures. The wire codes
have no relation to the app's export-XML `macro_type` values (`1`=disable,
`2`=default) — the XML is the local-DB format, the wire table is the keyboard
format. The macro binding carries **no slot number**: the L99 appears to have
a single macro slot.

## The macro table (opcodes `0x19` + `0x15`)

One write round per keystroke while recording, then a final one on save —
each round rewrites the whole slot content, so the rounds grow cumulatively.
Per round:

```
0x19 (0 blocks)  ->  0x15 with byte[8] = 9..10  ->  COMMIT (0x02)
```

The macro session is opened with one `BEGIN (0x18)` and never sends `END
(0xF0)` — the app just starts a new `BEGIN` session for the follow-up `0x11`
profile write and ends that one. Round layout (9-10 blocks; the last carries
`AA 55` at 62-63):

| Block | Offset | Content |
|---|---|---|
| 0 | 0 | header: `90 01 00 00 b8 01 00 00` = two 16-bit LE offsets `{0x0190, 0x01b8}` = table offsets 400 and 440 (the marker and count positions below) |
| 1-5 | 64-383 | zero padding |
| 6 | 384 | marker `0x08` at 400 (constant in all 7 observed rounds); 4 events at 410, 418, 426, 434 (8-byte stride); 8-byte count field at 440: `4 * (keys recorded in the current session)` — `0x04`, `0x08`, `0x0C`, ... `0x18` for the 6 recorded keys |
| 7+ | 448.. | further events, same continuous 8-byte stride (448, 456, 464, ...) |

Event (8 bytes, continuous stride from 410):

```
00 00 <usage> <0x30|0xB0> <delay> 00 00 0x50
```

| Byte | Meaning |
|---|---|
| 2 | HID keyboard usage (0x1B = X, 0x1C = Y, 0x1D = Z ...) |
| 3 | `0xB0` key-down / `0x30` key-up (the `0x80` bit is the pressed flag) |
| 4 | delay, ms (`0x0A` = 10, the app's default record interval, matching the export XML's `delay_time`) |
| 7 | constant `0x50` |

Observed behaviour worth noting: recording a *new* macro kept the previously
stored slot content at the head of every write — the slot for "go" was
followed by the growing "xxyyzz" events — while the count byte tracked only
the new recording's keys. The keyboard plays back whatever the slot holds.

## Command list (complete opcode reference, cable `0C45:800A` iface 3)

| Opcode | Name | Direction | Blocks | Purpose |
|---|---|---|---|---|
| `0x18` | begin session | out | 0 | open a write session |
| `0x28` | RTC set | out | 1 | clock + panel monitor/weather readout (see `system_monitor_block.md`) |
| `0x23` | colour set | out | 9 | persistent per-key colour table (see `color_stream.md`/README) |
| `0xF5` | colour query | in | 9 | read back current per-key colour (polled ~27x/s) |
| `0x20` | colour stream | out | 8 | session-less realtime colour stream |
| `0x13` | effect select | out | 1 | built-in lighting effect + colour/speed/brightness |
| `0x17` | settings write | out | 1 | sleep timer + response time (see `settings_write.md`) |
| `0x78` | audio feed | out | 1 | 23-band spectrum for the panel (see `audio_spectrum_block.md`) |
| `0x11` | profile write | out | 9 | key-remap table, 4-byte entries at `key_index * 4` (this note) |
| `0x19` | macro preamble | out | 0 | per-macro-write companion of `0x15` (this note) |
| `0x15` | macro write | out | 9-10 | macro slot table with 8-byte key events (this note) |
| `0x27` | unknown | out | 9 | same table shape as `0x11`, seen only at startup with an all-zero table; Fn-layer table is the working hypothesis, untested (Wine menu handling made the Fn-layer UI unusable) |
| `0x02` | commit | out | 0 | apply; reply carries a 16-bit LE monotonic counter at offset 4 |
| `0xF0` | end session | out | 0 | close a write session |
| `0x00` | unknown | — | — | still never observed in any capture |

## Still open

- `0x27`'s purpose (Fn layer suspected) and the Fn-layer entry encoding
- Type codes for the remaining key types (mouse, shortcuts, text, multi-key)
- Macro play parameters — the app's "play once / multiple / release to stop /
  loop count" options never appeared on the wire during save; they may be
  host-side, or hidden in the constant `0x08`/`0x50` markers
- Mouse-action macro events (the mouse equivalents of the keyboard events)
- `parse_shim_log.py --verify` does not yet know `0x11`/`0x15`/`0x19`/`0x27`;
  the byte layouts above are from manual analysis of the listed logs
