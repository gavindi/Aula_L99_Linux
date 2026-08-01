"""CPU/GPU load sampling for the touchscreen's system-monitor readout.

Linux-only, no dependencies. CPU busy-percent comes from deltas of
`/proc/stat`'s aggregate `cpu` line; GPU busy-percent comes from `nvidia-smi`
when it is on PATH, otherwise from the first drm `gpu_busy_percent` sysfs node
(AMD and recent Intel expose one). If neither GPU source exists, GPU load stays
0 -- the same "nothing to report" the vendor app sends when it has no data.

A `MonitorSampler` is the `load_fn` the GUI passes to
`workers.MonitorStreamWorker`: it is a plain callable returning a
`kb_protocol.MonitorData`, safe to run on the worker thread, keeping only its
own CPU-delta counters as state. Nothing here talks to the keyboard or panel.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from aula_l99_hacky.protocol import MonitorData


def _cpu_busy_percent(prev_idle: int | None, prev_total: int | None) -> tuple[int, int, int] | None:
    """Read /proc/stat's aggregate cpu line and return (idle, total, percent).

    `percent` is the busy share of the wall time since the caller's previous
    sample. Returns None when the file is unreadable or the counters went
    backwards (a suspend, or a first read that has no delta).
    """
    try:
        with open("/proc/stat", encoding="ascii") as fh:
            fields = fh.readline().split()
    except OSError:
        return None
    try:
        values = [int(v) for v in fields[1:]]
    except ValueError:
        return None
    idle = values[3] + values[4]
    total = sum(values)
    if prev_idle is None or prev_total is None or total < prev_total:
        return idle, total, 0
    delta_total = total - prev_total
    if delta_total <= 0:
        return idle, total, 0
    percent = (delta_total - (idle - prev_idle)) * 100 / delta_total
    return idle, total, max(0, min(100, int(percent)))


class MonitorSampler:
    """Callable returning a MonitorData with cpu_load/gpu_load filled in.

    First call returns a CPU load of 0 -- there is no prior sample to form a
    delta against -- so the panel shows a real value from the second 5s tick
    onwards. The GPU source (nvidia-smi subprocess or a drm sysfs node) is
    resolved on first call and kept.
    """

    def __init__(self) -> None:
        self._cpu_idle: int | None = None
        self._cpu_total: int | None = None
        self._gpu_load: int | None = None
        self._gpu_probe = None

    def __call__(self) -> MonitorData:
        return MonitorData(cpu_load=self.cpu_load(), gpu_load=self.gpu_load())

    def cpu_load(self) -> int:
        sampled = _cpu_busy_percent(self._cpu_idle, self._cpu_total)
        if sampled is None:
            return 0
        self._cpu_idle, self._cpu_total, percent = sampled
        return percent

    def gpu_load(self) -> int:
        if self._gpu_load is not None:
            return self._gpu_load
        probe = self._gpu_probe
        if probe is None:
            probe = _resolve_gpu_probe()
            self._gpu_probe = probe
        if probe is None:
            self._gpu_load = 0
            return 0
        try:
            value = probe()
        except (OSError, ValueError, subprocess.SubprocessError):
            self._gpu_load = 0
            return 0
        self._gpu_load = max(0, min(100, value))
        return self._gpu_load


def _resolve_gpu_probe():
    """Return a zero-arg callable giving GPU busy-percent, or None.

    Prefers nvidia-smi when installed; otherwise the first drm
    gpu_busy_percent node. The callable may raise OSError/ValueError, which
    gpu_load() turns into a 0 for that tick.
    """
    if shutil.which("nvidia-smi"):
        def _nvidia_smi() -> int:
            completed = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2, check=False,
            )
            first_line = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
            return int(first_line.split(",")[0])
        return _nvidia_smi

    nodes = sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"))
    if nodes:
        node = nodes[0]
        def _drm_sysfs() -> int:
            return int(node.read_text(encoding="ascii").strip())
        return _drm_sysfs

    return None
