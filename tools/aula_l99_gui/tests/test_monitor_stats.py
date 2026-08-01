from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from aula_l99_gui.monitor_stats import MonitorSampler


def _stat_line(*values: int) -> str:
    return "cpu  " + " ".join(str(v) for v in values) + "\n"


def _two_samples(busy_delta: int) -> list[str]:
    # Two /proc/stat cpu lines whose deltas are `busy_delta` busy ticks and
    # 700 idle ticks, i.e. busy_delta / (busy_delta + 700) percent.
    return [
        _stat_line(400, 0, 0, 1000, 0, 0, 0, 0),  # user, nice, sys, idle, ...
        _stat_line(400 + busy_delta, 0, 0, 1000 + 700, 0, 0, 0, 0),
    ]


def test_cpu_load_first_sample_is_zero_then_delta_percent(monkeypatch):
    lines = iter(_two_samples(busy_delta=300))
    monkeypatch.setattr("builtins.open", _fake_open_for(lines))

    sampler = MonitorSampler()
    sampler._gpu_load = 0

    assert sampler.cpu_load() == 0  # no prior sample yet
    assert sampler.cpu_load() == 30  # 300 of 1000 ticks busy since last sample


def test_cpu_load_returns_zero_when_proc_stat_unreadable(monkeypatch):
    def broken_open(path, *args, **kwargs):
        raise OSError("no /proc")

    monkeypatch.setattr("builtins.open", broken_open)

    sampler = MonitorSampler()
    sampler._gpu_load = 0

    assert sampler.cpu_load() == 0


def test_gpu_load_prefers_nvidia_smi(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        assert "nvidia-smi" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=" 42\n", stderr="")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr("subprocess.run", fake_run)

    sampler = MonitorSampler()
    assert sampler.gpu_load() == 42
    assert sampler.gpu_load() == 42  # cached, no second probe


def test_gpu_load_falls_back_to_drm_sysfs(monkeypatch):
    node = Path("/sys/class/drm/card1/device/gpu_busy_percent")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(
        "pathlib.Path.glob",
        lambda self, pattern: [node] if str(self) == "/sys/class/drm" else [],
    )
    monkeypatch.setattr(Path, "read_text", lambda self, **kwargs: "63\n")

    sampler = MonitorSampler()
    assert sampler.gpu_load() == 63


def test_gpu_load_is_zero_with_no_source(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.glob", lambda self, pattern: [])

    sampler = MonitorSampler()
    assert sampler.gpu_load() == 0


def test_gpu_load_clamps_out_of_range(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="140\n", stderr="")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr("subprocess.run", fake_run)

    sampler = MonitorSampler()
    assert sampler.gpu_load() == 100


def test_call_returns_monitor_data(monkeypatch):
    from aula_l99_hacky.protocol import MonitorData

    lines = iter(_two_samples(busy_delta=0))
    monkeypatch.setattr("builtins.open", _fake_open_for(lines))
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.glob", lambda self, pattern: [])

    sampler = MonitorSampler()
    data = sampler()

    assert isinstance(data, MonitorData)
    assert data.cpu_load == 0
    assert data.gpu_load == 0


def _fake_open_for(lines):
    def fake_open(path, *args, **kwargs):
        assert str(path) == "/proc/stat"

        class _Reader:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def readline(self):
                try:
                    return next(lines)
                except StopIteration:
                    pytest.fail("read past the faked /proc/stat samples")

        return _Reader()

    return fake_open
