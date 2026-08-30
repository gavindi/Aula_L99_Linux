"""Pure-DSP tests for audio_spectrum.py plus a worker test for the 0x78 path.

The Goertzel tests use a synthetic full-scale sine at one band centre and
assert that band dominates while its neighbours stay low, and that silence is
all zeroes -- the same checks a real analyser's correctness hangs on. The
worker test drives the real AudioSpectrumWorker with a fake transport and a
stubbed arecord, so it exercises the actual transaction shape the panel sees.
"""
import math
import struct
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

from aula_l99_gui import audio_spectrum, workers
from aula_l99_hacky import protocol as kb_protocol

RATE = audio_spectrum.SAMPLE_RATE
CHUNK = audio_spectrum.CHUNK_SAMPLES


def _sine(level: int, freq: float, count: int = CHUNK) -> list[int]:
    return [int(level * math.sin(2 * math.pi * freq * i / RATE)) for i in range(count)]


def test_band_count_matches_the_panels_render():
    assert audio_spectrum.SPECTRUM_BAND_COUNT == 17
    assert len(audio_spectrum.band_frequencies()) == 17
    # The wire block carries up to 23 (see kb_protocol.AUDIO_BAND_COUNT); the
    # panel renders 17, so the two counts are deliberately different ends of
    # one transfer.
    assert audio_spectrum.SPECTRUM_BAND_COUNT < kb_protocol.AUDIO_BAND_COUNT


def test_bands_are_log_spaced_ascending():
    bands = audio_spectrum.band_frequencies()
    assert bands == sorted(bands)
    assert all(b < n for b, n in zip(bands, bands[1:]))
    assert bands[0] == audio_spectrum.SPECTRUM_MIN_FREQ
    assert bands[-1] == audio_spectrum.SPECTRUM_MAX_FREQ


def test_full_scale_sine_lights_only_its_own_band():
    bands = audio_spectrum.band_frequencies()
    # Bands 8 and 16 only: the low bands sit inside one ~23Hz FFT bin of each
    # other (30/44/66Hz), so a tone there smears into its neighbours -- real
    # analyser behaviour, not a bug. Mid and high bands are well separated.
    for centre in (8, 16):
        levels = audio_spectrum.levels_from_samples(_sine(32767, bands[centre]), bands=bands)
        assert levels[centre] > 90, (centre, levels)
        assert max(levels[:centre]) < 15, (centre, levels)
        assert max(levels[centre + 1:] or [0]) < 15, (centre, levels)


def test_lower_amplitude_gives_a_lower_level():
    bands = audio_spectrum.band_frequencies()
    full = audio_spectrum.levels_from_samples(_sine(32767, bands[8]), bands=bands)
    quiet = audio_spectrum.levels_from_samples(_sine(3277, bands[8]), bands=bands)
    assert full[8] > quiet[8]
    assert quiet[8] < full[8]


def test_silence_is_all_zeroes():
    levels = audio_spectrum.levels_from_samples([0] * CHUNK)
    assert levels == [0] * audio_spectrum.SPECTRUM_BAND_COUNT


def test_levels_stay_in_range():
    bands = audio_spectrum.band_frequencies()
    # A signal louder than full scale (clipping) must clamp, not overflow.
    levels = audio_spectrum.levels_from_samples(_sine(40000, bands[8]), bands=bands)
    assert all(0 <= level <= 100 for level in levels)


def test_pcm_path_round_trips_the_sample_path():
    bands = audio_spectrum.band_frequencies()
    samples = _sine(32767, bands[8])
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    assert audio_spectrum.levels_from_pcm(pcm, bands=bands) == (
        audio_spectrum.levels_from_samples(samples, bands=bands))


def test_parse_arecord_devices_reads_real_output_shape():
    text = (
        "**** List of CAPTURE Hardware Devices ****\n"
        "card 1: AG06AG03 [AG06/AG03], device 0: USB Audio [USB Audio]\n"
        "  Subdevices: 1/1\n"
        "  Subdevice #0: subdevice #0\n"
        "card 2: Generic [HD-Audio Generic], device 0: ALC1220 Analog [ALC1220 Analog]\n"
        "  Subdevices: 1/1\n"
    )
    devices = audio_spectrum.parse_arecord_devices(text)
    assert devices == [
        audio_spectrum.CaptureDevice("AG06/AG03 USB Audio", "plughw:1,0"),
        audio_spectrum.CaptureDevice("HD-Audio Generic ALC1220 Analog", "plughw:2,0"),
    ]


def test_parse_arecord_devices_empty_on_no_devices():
    assert audio_spectrum.parse_arecord_devices("") == []
    assert audio_spectrum.parse_arecord_devices(
        "**** List of CAPTURE Hardware Devices ****\n") == []


def test_arecord_command_is_raw_mono_s16():
    cmd = audio_spectrum.arecord_command("plughw:1,0")
    assert cmd[0] == "arecord"
    assert "-D" in cmd and cmd[cmd.index("-D") + 1] == "plughw:1,0"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "raw"
    assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "S16_LE"


# Trimmed real `pw-dump` fixtures (captured live, props unrelated to this
# parsing dropped): one sink (a loopback source), two application streams
# (one with a track title, one without), and one non-Node object that a real
# dump would also contain and which must be ignored.
_PW_SINK_NODE = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {
        "object.serial": 71,
        "node.name": "alsa_output.usb-Yamaha-00.iec958-stereo",
        "node.description": "AG06/AG03 Digital Stereo (IEC958)",
        "node.nick": "AG06/AG03",
        "media.class": "Audio/Sink",
    }},
}
_PW_APP_STREAM_WITH_TITLE = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {
        "object.serial": 10978,
        "node.name": "Shortwave",
        "application.name": "Shortwave",
        "media.title": "Peter W - Last Ninja",
        "media.class": "Stream/Output/Audio",
    }},
}
_PW_APP_STREAM_NO_TITLE = {
    "type": "PipeWire:Interface:Node",
    "info": {"props": {
        "object.serial": 5208,
        "node.name": "speech-dispatcher-dummy",
        "application.name": "speech-dispatcher-dummy",
        "media.name": "playback",
        "media.class": "Stream/Output/Audio",
    }},
}
_PW_NON_NODE_OBJECT = {
    "type": "PipeWire:Interface:Port",
    "info": {"props": {"media.class": "Audio/Sink"}},
}


def test_parse_pipewire_devices_reads_a_sink_as_a_loopback_source():
    devices = audio_spectrum.parse_pipewire_devices([_PW_SINK_NODE])
    assert devices == [
        audio_spectrum.CaptureDevice(
            "Loopback: AG06/AG03 Digital Stereo (IEC958)", "71", kind="pipewire"),
    ]


def test_parse_pipewire_devices_reads_application_streams():
    devices = audio_spectrum.parse_pipewire_devices(
        [_PW_APP_STREAM_WITH_TITLE, _PW_APP_STREAM_NO_TITLE])
    assert devices == [
        audio_spectrum.CaptureDevice(
            "App: Shortwave – Peter W - Last Ninja", "10978", kind="pipewire"),
        audio_spectrum.CaptureDevice(
            "App: speech-dispatcher-dummy", "5208", kind="pipewire"),
    ]


def test_parse_pipewire_devices_ignores_non_node_objects():
    assert audio_spectrum.parse_pipewire_devices([_PW_NON_NODE_OBJECT]) == []


def test_pw_record_command_is_raw_mono_s16():
    cmd = audio_spectrum.pw_record_command("71")
    assert cmd[0] == "pw-record"
    assert "--target" in cmd and cmd[cmd.index("--target") + 1] == "71"
    assert "--channels" in cmd and cmd[cmd.index("--channels") + 1] == "1"
    assert "--format" in cmd and cmd[cmd.index("--format") + 1] == "s16"
    assert "--raw" in cmd
    assert cmd[-1] == "-"


class _FakePopen:
    """Minimal subprocess.Popen stand-in: yields one PCM chunk then EOF."""

    def __init__(self, data: bytes):
        self._data = data
        self._sent = False
        self._killed = threading.Event()
        self.stdout = _FakeStream(data, self)
        self.stderr = _FakeStream(b"", self)

    def poll(self):
        return None if not self._sent else 0

    def terminate(self):
        self._killed.set()


class _FakeStream:
    def __init__(self, data: bytes, proc):
        self._data = data
        self._proc = proc
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if self._proc._killed.is_set() and self._pos >= len(self._data):
            return b""
        if self._pos >= len(self._data):
            if self._proc._sent:
                return b""
            self._proc._sent = True
            return b""
        if n is None or n < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            self._proc._sent = True
            return chunk
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        if self._pos >= len(self._data):
            self._proc._sent = True
        return chunk


class _FakeHidraw:
    """Records feature-report writes; acks every expect_reply command.

    Mirrors the real HidrawTransport's close semantics: a write after the
    context manager has exited is a bug (the real transport's `_fd` is None
    and set_feature asserts), so the fake raises instead of recording it.
    """

    def __init__(self):
        self.written = []
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._closed = True
        return False

    def set_feature(self, payload: bytes) -> None:
        assert not self._closed, "set_feature after transport closed"
        self.written.append(bytes(payload))

    def get_feature(self, report_id: int, size: int) -> bytes:
        assert not self._closed, "get_feature after transport closed"
        reply = bytearray(kb_protocol.PACKET_SIZE)
        reply[0] = kb_protocol.CMD_PREFIX
        reply[1] = self.written[-1][1]
        reply[kb_protocol.ACK_OFFSET] |= kb_protocol.ACK_FLAG
        return bytes([kb_protocol.REPORT_ID]) + bytes(reply)


def test_audio_spectrum_worker_sends_audio_frames():
    bands = audio_spectrum.band_frequencies()
    samples = _sine(32767, bands[8])
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    # Long enough for the loop to read at least one chunk then break on EOF.
    pcm = pcm + pcm

    fake_proc = _FakePopen(pcm)
    fake_hidraw = _FakeHidraw()
    worker = workers.AudioSpectrumWorker(
        "/dev/hidraw6", ["arecord", "-l"], audio_spectrum.levels_from_pcm)

    frames = []
    results = {}
    worker.frame.connect(lambda levels: frames.append(levels))
    worker.finished.connect(lambda ok, msg: results.setdefault("finished", (ok, msg)))

    with patch.object(workers.subprocess, "Popen", lambda *a, **k: fake_proc):
        with patch.object(workers, "HidrawTransport", lambda *a, **k: fake_hidraw):
            worker.run()

    assert results["finished"][0] is True
    assert frames, "expected at least one frame emitted"

    # Every write must be a member of the audio frame transaction sequence
    # (commit -> 0x78 -> one block), with the block carrying the 17 levels.
    written = [w[1:] for w in fake_hidraw.written]  # drop the report-id byte
    i = 0
    frames_seen = 0
    while i < len(written):
        header = written[i]
        assert header[0] == kb_protocol.CMD_PREFIX
        opcode = header[1]
        if opcode == kb_protocol.OP_COMMIT:
            pass
        elif opcode == kb_protocol.OP_AUDIO:
            assert header[8] == 1  # one data block follows
            block = written[i + 1]
            assert block[0:3] == bytes([
                kb_protocol.AUDIO_RHYTHM_DEFAULT,
                kb_protocol.AUDIO_BACKGROUND_MODE_DEFAULT,
                kb_protocol.AUDIO_SCALE_DEFAULT,
            ])
            levels = block[3:3 + audio_spectrum.SPECTRUM_BAND_COUNT]
            assert list(levels) == frames[frames_seen]
            # Bands 17..22 stay zero -- the panel ignores them, and the block
            # is zero-padded from 17 up to the full 23.
            assert block[3 + audio_spectrum.SPECTRUM_BAND_COUNT:
                         3 + kb_protocol.AUDIO_BAND_COUNT] == bytes(
                kb_protocol.AUDIO_BAND_COUNT - audio_spectrum.SPECTRUM_BAND_COUNT)
            i += 2
            frames_seen += 1
        else:
            raise AssertionError(f"unexpected opcode 0x{opcode:02x} in write stream")
        i += 1

    assert frames_seen == len(frames)
    # The first emitted frame should be the loud band-8 one.
    assert frames[0][8] > 90


def test_audio_spectrum_worker_sends_configured_music_settings():
    """The worker carries the Music tab's Rhythm / Background Mode / Amplitude
    / Background Brightness onto every frame's block, and scales levels to the
    amplitude before sending (so the levels agree with the scale byte)."""
    bands = audio_spectrum.band_frequencies()
    samples = _sine(32767, bands[8])
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    pcm = pcm + pcm

    fake_proc = _FakePopen(pcm)
    fake_hidraw = _FakeHidraw()
    worker = workers.AudioSpectrumWorker(
        "/dev/hidraw6", ["arecord", "-l"], audio_spectrum.levels_from_pcm,
        rhythm=9, background_mode=3, amplitude=50, background_brightness=7)

    results = {}
    worker.finished.connect(lambda ok, msg: results.setdefault("finished", (ok, msg)))

    with patch.object(workers.subprocess, "Popen", lambda *a, **k: fake_proc):
        with patch.object(workers, "HidrawTransport", lambda *a, **k: fake_hidraw):
            worker.run()

    assert results["finished"][0] is True
    written = [w[1:] for w in fake_hidraw.written]
    blocks = [
        written[i + 1] for i, w in enumerate(written)
        if w[1] == kb_protocol.OP_AUDIO
    ]
    assert blocks, "expected at least one audio block"
    for block in blocks:
        assert block[kb_protocol.AUDIO_OFF_RHYTHM] == 9
        assert block[kb_protocol.AUDIO_OFF_BACKGROUND_MODE] == 3
        assert block[kb_protocol.AUDIO_OFF_SCALE] == 50
        assert block[kb_protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS] == 7
        # Levels are scaled to amplitude 50, so none may exceed the scale byte.
        assert max(block[3:3 + audio_spectrum.SPECTRUM_BAND_COUNT]) <= 50


def test_audio_spectrum_worker_settings_apply_mid_stream():
    """A running worker must pick up set_music_settings() changes from the
    next frame on -- that is how the Music tab edits its four controls while
    a capture is live (no restart)."""
    bands = audio_spectrum.band_frequencies()
    samples = _sine(32767, bands[8])
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    # Enough chunks for several frames: the first carries the constructor's
    # settings, the rest the mid-stream update.
    pcm = pcm * 6

    fake_proc = _FakePopen(pcm)
    fake_hidraw = _FakeHidraw()
    worker = workers.AudioSpectrumWorker(
        "/dev/hidraw6", ["arecord", "-l"], audio_spectrum.levels_from_pcm,
        rhythm=8, background_mode=4, amplitude=100, background_brightness=0)

    frames = []
    updated = False

    def _update_after_first_frame(levels):
        nonlocal updated
        frames.append(levels)
        if not updated:
            updated = True
            worker.set_music_settings(
                rhythm=9, background_mode=3, amplitude=50,
                background_brightness=7)

    worker.frame.connect(_update_after_first_frame)
    worker.finished.connect(lambda *a: None)

    with patch.object(workers.subprocess, "Popen", lambda *a, **k: fake_proc):
        with patch.object(workers, "HidrawTransport", lambda *a, **k: fake_hidraw):
            worker.run()

    written = [w[1:] for w in fake_hidraw.written]
    blocks = [
        written[i + 1] for i, w in enumerate(written)
        if w[1] == kb_protocol.OP_AUDIO
    ]
    # The frame signal fires *after* its block is written, so the first block
    # carries the constructor's settings and every later one the update.
    first, *rest = blocks
    assert first[kb_protocol.AUDIO_OFF_RHYTHM] == 8
    assert first[kb_protocol.AUDIO_OFF_BACKGROUND_MODE] == 4
    assert first[kb_protocol.AUDIO_OFF_SCALE] == 100
    assert first[kb_protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS] == 0
    assert max(first[3:3 + audio_spectrum.SPECTRUM_BAND_COUNT]) > 50
    assert rest, "expected later frames carrying the updated settings"
    for block in rest:
        assert block[kb_protocol.AUDIO_OFF_RHYTHM] == 9
        assert block[kb_protocol.AUDIO_OFF_BACKGROUND_MODE] == 3
        assert block[kb_protocol.AUDIO_OFF_SCALE] == 50
        assert block[kb_protocol.AUDIO_OFF_BACKGROUND_BRIGHTNESS] == 7
        # Levels are rescaled to the new amplitude, so they agree with the
        # new scale byte and none may exceed it.
        assert max(block[3:3 + audio_spectrum.SPECTRUM_BAND_COUNT]) <= 50


def test_audio_spectrum_worker_reports_arecord_failure():
    fake_proc = _FakePopen(b"")
    fake_hidraw = _FakeHidraw()
    worker = workers.AudioSpectrumWorker(
        "/dev/hidraw6", ["arecord", "-l"], audio_spectrum.levels_from_pcm)

    results = {}
    worker.finished.connect(lambda ok, msg: results.setdefault("finished", (ok, msg)))

    with patch.object(workers.subprocess, "Popen", lambda *a, **k: fake_proc):
        with patch.object(workers, "HidrawTransport", lambda *a, **k: fake_hidraw):
            worker.run()

    # No audio data and no writes: the worker must end cleanly, not spin.
    assert results["finished"][0] is True
    assert fake_hidraw.written == []
