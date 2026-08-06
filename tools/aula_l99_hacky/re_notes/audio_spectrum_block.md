# The audio spectrum block (opcode 0x78)

Decoded from `wireshark_dumps/save_to_gif_17.pcapng`, which caught the vendor
app feeding the panel's spectrum analyser while music played: 137 frames over
about 6.5 seconds. Everything below reproduces all 137 byte-for-byte.

**Confirmed on hardware.** Every claim below was read off one capture plus a
cross-check against `DeviceDriver.exe`, then verified by sending frames to a
wired `0C45:800A` keyboard and watching the panel:

- The transaction shape holds: the commit and the `0x78` command come back
  acked (byte 3 = 0x01), and the data block comes back echoed verbatim with
  the ack bit clear, exactly as the capture predicted.
- There are **23 band levels on the wire, low frequency first**, and driving
  one band at a time lights the expected bar in order.
- The panel's analyser has **17 on-screen segments, edge to edge**, mapping to
  wire bands 0..16. Bands 17..22 produce no visible change: the keyboard
  accepts all 23 numbers and the display renders only the low 17 of them.

The wire format is unchanged by that last point -- `--spectrum` still sends
up to `AUDIO_BAND_COUNT` (23) values because that is what the feed carries;
the 17-segment display is a property of the panel's analyser, not of the
protocol.

## The host does the FFT

The keyboard receives 23 numbers. It never sees audio.

`DeviceDriver.exe` imports `ole32` and carries `CLSID_MMDeviceEnumerator`,
`IID_IAudioClient` and `IID_IAudioCaptureClient` -- WASAPI, so it opens a
loopback capture on the default render device. It does *not* import any of
`waveInOpen` and friends; its only `WINMM` imports are `timeGetTime`,
`timeBeginPeriod` and `timeEndPeriod`, which are the timer-granularity calls
that show up all over this app.

So this feed cannot be reproduced by replaying packets alone if what you want
is a working visualiser -- you need an audio source and an FFT on the Linux
side. What the capture gives you is the wire format to send the result to.

## Transaction shape

Three feature reports per frame, repeating with no session framing around
them, at a median 47ms apart (about 21 frames/s):

```
04 02 00 00 ...        commit                       -> 04 02 00 01 ...
04 78 00 00 ... 01     OP_AUDIO, one block follows  -> 04 78 00 01 ... 01
04 08 64 <23 levels>   the data block               -> echoed verbatim
```

Note the commit comes *before* the command. That is the same shape as the
`OP_COLOR_QUERY` poll loop and the opposite of the realtime colour stream
(`0x20`), which commits after its blocks. Three different opcodes on this
channel, three different framings; see the note at the top of `protocol.py`.

An RTC write (`0x18`, `0x28`, block) drops into the middle of this loop at
packets 662-675 and the spectrum stream resumes without a hiccup, so the two
do not need sequencing against each other. That is worth knowing given that
`OP_COLOR_QUERY` polling *does* disturb running effects.

## The third packet is a data block, not a command

It begins `0x04`, which is `CMD_PREFIX`, and it would be easy to read it as a
command with opcode `0x08`. It is not, on two independent grounds:

- **The device does not ack it.** Every real command in this capture --
  `0x02`, `0x18`, `0x28`, `0x78` -- comes back from a `GET_REPORT` with byte 3
  set to `0x01`. This packet comes back byte-for-byte identical, ack bit
  clear, exactly as the RTC *data block* at packet 675 does.
- **Byte 8 is not a block count.** In a command header byte 8 says how many
  raw blocks follow. Here it ranges 0..38 across frames, tracking the music.

Read as a block, everything is consistent: `0x78` announces one block, and the
block is the frame.

## Block layout

```
04 08 64 <23 level bytes> <38 zero bytes>
```

| offset | captured value | reading |
|-------:|----------------|---------|
| 0      | `0x04`         | constant in all 137 frames |
| 1      | `0x08`         | constant in all 137 frames |
| 2      | `0x64` = 100   | constant in all 137 frames |
| 3..25  | 0..100         | 23 band levels, low frequency first |
| 26..63 | zero           | never written |

**There is no `AA 55` trailer.** This is the only outbound block in the
protocol without one, and it is not an artefact of the capture: bytes 26..63
are zero in every frame, so the trailer is absent rather than displaced.

### Band ordering is not in doubt

The opening frames are loud at band 0 and silent above band 4
(`25 30 12 4 1 0 0 ...`), and packet 1770 is the reverse -- silent below band
8, loud above (`0 0 0 0 0 0 0 0 8 27 32 32 24 33 11 3 0 ...`). Low frequency
first. Both of those frames are pinned in the tests for exactly this reason.

### Bytes 0..2 are the soft part

These are named constants in `protocol.py` rather than inlined, because two of
them are only provisionally constant:

- **Byte 1 = `0x08`** collides with `EFFECT_NAMES[0x08] == "spectrum"`. The
  vendor app has a "Music Rhythm" tab (language string 56) whose controls
  include "Rhythm" (102) and "Amplitude" (103), so a rhythm-style selector
  leaking into byte 1 is plausible. So is coincidence.
- **Byte 2 = `0x64`** is either the full-scale value the levels are relative
  to, or that tab's Amplitude slider, which is also a 0..100 control that
  would sit at 100 by default. One capture at one setting cannot separate
  those two readings.

`build_audio_blocks()` rejects a level above the scale byte, which is right
under the first reading and too strict under the second. If it turns out to be
Amplitude, drop the check rather than widening it quietly.

I looked for the builder in `DeviceDriver.exe` to settle this -- searching for
a `C6 /r` byte store of immediate `0x04`, `0x08` and `0x64` within one window
-- and found nothing. That is weak evidence that these come from variables
rather than literals, which would favour the settings reading. Weak because
plenty of other encodings would also miss.

## Level quantisation

Across both captures the levels take only 37 distinct values:

```
0 1 3 4 6 8 9 11 12 14 16 17 19 20 22 24 25 27 28 30 32 33 35 36 38 40 41 43
44 46 48 49 51 56 57 60 65
```

Every one is exactly `floor(n * 8 / 5)`. So the app's internal amplitude is an
integer of about 0..62 scaled by 1.6 to land on a 0..100 range, and the real
resolution of this feed is roughly 63 steps rather than 101. Nothing enforces
this -- an off-quantum level is presumably still legal -- but it is what the
vendor would have sent, and `test_every_captured_level_fits_the_vendors_quantum`
guards the reading.

## What is still unknown

- **How the stream is enabled.** The capture starts mid-stream: packet 31 is
  already a read-back of a spectrum block, before any `SET_REPORT`. Nothing in
  the capture turns it on or off. An RTC write during the stream carried
  `view` = 1, the same as everywhere else, so it is not a distinct screen view
  in the sense byte 1 of the RTC block means.
- **What consumes it, and the 17/23 split.** The panel's analyser is now
  confirmed as the consumer, and it renders only **17 segments** for wire
  bands 0..16, edge to edge; bands 17..22 have no visible effect. Whether the
  keyboard itself also lights up remains untested -- per-key colour has its own
  opcodes (`0x23` persistent, `0x20` realtime), and the 23 bands do not match
  the 16-column key matrix, so it was never a strong candidate. Why the feed
  carries 23 bands but the display draws 17 is unknown; the obvious guess is
  the vendor's FFT divides the spectrum into more bands than the analyser's
  widget renders, so the high six are simply not drawn.
- **What happens to a frame that is never followed by another.** `--spectrum`
  sends one frame by default; `--spectrum-hold` resends it because a lone
  frame may only be on screen for a frame period. On the panel it **holds**:
  stop the stream and the analyser freezes on the last frame it received,
  bars included. The GUI's Music tab works around this by sending one
  all-zero frame on stop, which drops the bars back to zero. Whether the
  panel eventually blanks by itself, and how long that takes, is untested.
- **Whether the 47ms period matters.** It is the vendor's rate, not
  necessarily a requirement, and the same app leaves ~36.7ms between packets
  everywhere for reasons that turned out to be host-side.
