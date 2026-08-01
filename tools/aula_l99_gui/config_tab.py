"""Config tab: the settings that aren't about one particular piece of
content -- the keyboard's onboard clock and the colour-poll rate -- plus the
consolidated debug log every other control tab writes into instead of
keeping its own isolated log widget.

Pure UI as far as the hardware is concerned: both controls are forwarded as
signals and carried out by KeyboardTab, which owns the poll thread they'd
otherwise race (see its module docstring).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .debug_log import DebugLog
from .device_tab import DeviceSelector
from .keyboard_tab import (
    DEFAULT_POLL_INTERVAL_MS,
    MAX_POLL_INTERVAL_MS,
    MIN_POLL_INTERVAL_MS,
)


class ConfigTab(QWidget):
    busy_changed = Signal(bool)  # never emitted; keeps main_window's tab interface uniform
    set_clock_requested = Signal()
    poll_interval_changed = Signal(int)
    monitor_toggled = Signal(bool)  # checked = stream CPU/GPU load

    def __init__(self, selector: DeviceSelector, debug_log: DebugLog) -> None:
        super().__init__()
        self._device_ready = False
        self._external_busy = False

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_keyboard_group())
        layout.addWidget(self._build_monitor_group())
        layout.addWidget(self._build_poll_group())
        layout.addWidget(self._build_log_group(debug_log), stretch=1)

        selector.changed.connect(self._on_device_changed)
        self._sync_actions()

    # -- UI construction ------------------------------------------------

    def _build_keyboard_group(self) -> QGroupBox:
        group = QGroupBox("Keyboard Clock")
        column = QVBoxLayout(group)

        row = QHBoxLayout()
        self.set_clock_button = QPushButton("Set Clock to Now")
        self.set_clock_button.clicked.connect(self.set_clock_requested)
        row.addWidget(self.set_clock_button)
        row.addStretch(1)
        column.addLayout(row)

        # Fed by KeyboardTab.write_progress -- the write runs over there, but
        # the only button that starts one is right above this bar.
        self.progress_bar = QProgressBar()
        column.addWidget(self.progress_bar)
        return group

    def _build_monitor_group(self) -> QGroupBox:
        group = QGroupBox("System Monitor")
        column = QVBoxLayout(group)

        row = QHBoxLayout()
        # A checkbox toggle like the other boolean controls: checked = stream.
        # Driven by KeyboardTab, which owns the write path; the toggle only
        # forwards intent.
        self.monitor_toggle = QCheckBox("Send CPU/GPU Load")
        self.monitor_toggle.toggled.connect(self.monitor_toggled)
        row.addWidget(self.monitor_toggle)
        self.monitor_readout = QLabel("not running")
        row.addWidget(self.monitor_readout)
        row.addStretch(1)
        column.addLayout(row)

        # Fed by KeyboardTab.monitor_loaded with the load values of the most
        # recent send, so the readout is a live check rather than a promise.
        self._monitor_last = None
        return group

    def _build_poll_group(self) -> QGroupBox:
        group = QGroupBox("Colour Polling")
        row = QHBoxLayout(group)
        row.addWidget(QLabel("Update every (ms):"))
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(MIN_POLL_INTERVAL_MS, MAX_POLL_INTERVAL_MS)
        self.poll_interval_spin.setSingleStep(50)
        self.poll_interval_spin.setValue(DEFAULT_POLL_INTERVAL_MS)
        self.poll_interval_spin.valueChanged.connect(self.poll_interval_changed)
        row.addWidget(self.poll_interval_spin)
        row.addStretch(1)
        return group

    def _build_log_group(self, debug_log: DebugLog) -> QGroupBox:
        group = QGroupBox("Debug Log")
        group_layout = QVBoxLayout(group)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        group_layout.addWidget(self.log)

        debug_log.message.connect(self.log.appendPlainText)
        debug_log.cleared.connect(self.log.clear)
        return group

    # -- device handling --------------------------------------------------

    def _on_device_changed(self, status: str, enabled: bool) -> None:
        self._device_ready = enabled
        self._sync_actions()

    def set_external_busy(self, busy: bool) -> None:
        """Called by MainWindow with whether *any* tab is mid-operation. This
        tab runs nothing itself, so unlike the other tabs' own `_busy` that's
        the only busy state it has to gate on -- including its own clock
        write, which is another tab's `busy_changed` from here."""
        self._external_busy = busy
        self._sync_actions()

    def _sync_actions(self) -> None:
        self.set_clock_button.setEnabled(self._device_ready and not self._external_busy)
        # The monitor toggle must stay clickable while checked so the user can
        # stop the stream even though everything else is disabled for it.
        checked = self.monitor_toggle.isChecked()
        self.monitor_toggle.setEnabled(
            self._device_ready and (checked or not self._external_busy))
        self.poll_interval_spin.setEnabled(self._device_ready and not self._external_busy)

    def _on_monitoring_changed(self, monitoring: bool) -> None:
        """Sync the toggle with the stream's real state -- a stream can end
        itself (transport failure), and the toggle must not stay checked."""
        if self.monitor_toggle.isChecked() != monitoring:
            self.monitor_toggle.setChecked(monitoring)
        if not monitoring:
            self._monitor_last = None
        self._update_monitor_readout()

    def _on_monitor_loaded(self, cpu_load: int, gpu_load: int) -> None:
        self._monitor_last = (cpu_load, gpu_load)
        self._update_monitor_readout()

    def _update_monitor_readout(self) -> None:
        if self._monitor_last is None:
            self.monitor_readout.setText("not running")
            return
        cpu_load, gpu_load = self._monitor_last
        self.monitor_readout.setText(f"last sent: CPU {cpu_load}% · GPU {gpu_load}%")

    def show_write_progress(self, value: int, maximum: int) -> None:
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)

    @property
    def is_busy(self) -> bool:
        return False
