"""Keyboard tab: a live view of each key's current colour, polled at a
user-adjustable interval (default 100ms).

Clicking a key opens KeyAssignmentDialog, which writes a key-remap ("Key
Function") entry to the keyboard's profile table through this tab's usual
transaction path -- see re_notes/key_remap_macros.md in aula_l99_hacky for
that table's decoded layout.

The two controls that used to sit under that view -- "Set Clock to Now" and
the poll interval -- are on the Config tab now, driving this tab through
`set_clock_now()`/`set_poll_interval()`. The work itself stays here rather
than moving with them: the poll thread lives here, and so does the
write-behind-an-in-flight-read queue that keeps an RTC write from racing it
for the same hidraw handle.

Split out from lighting_tab.py, which is also keyed off the keyboard's
DeviceSelector but hosts the color/effect controls under the Lighting tab.
"""
from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
from datetime import datetime

import defusedxml.ElementTree as safe_ET
from PySide6.QtCore import QStandardPaths, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol

from . import key_layout, settings, theme
from .debug_log import DebugLog
from .device_tab import DeviceSelector
from .device_utils import KEYBOARD_PERMISSION_HINT
from .key_assignment_dialog import KeyAssignmentDialog
from .keyboard_overlay import KeyboardOverlay
from .monitor_stats import MonitorSampler
from .workers import (
    CallableResultWorker,
    KeyboardWorker,
    MonitorStreamWorker,
    read_colors,
    start_worker,
)

DEFAULT_POLL_INTERVAL_MS = 100
# The vendor app itself polls its colour-query opcode ~27x/s (~37ms) to drive
# its own preview (see protocol.py's OP_COLOR_QUERY note) -- this is the read
# side, not the flash-writing colour-set path protocol.py warns not to
# hammer. The spinner's floor (1ms) is far below that precedented rate; in
# practice each read's own HID round-trip time (open + several feature
# reports) dominates over the timer interval, and _poll_busy prevents ticks
# from overlapping if a read is still in flight when the next one fires.
MIN_POLL_INTERVAL_MS = 1
MAX_POLL_INTERVAL_MS = 5000

# The touchscreen's monitor readout is driven through this tab's RTC write
# path. The Config tab's spin box lets the user retune the cadence between
# these bounds; 5s is the default (the vendor app itself streams at ~1 Hz,
# but there's no requirement to match it here) and keeps the readout current
# without hammering the RTC block. The worker slices its inter-send sleep so
# stop() stays responsive regardless of period (see workers.py).
MIN_MONITOR_PERIOD_SECONDS = 1
MAX_MONITOR_PERIOD_SECONDS = 60
DEFAULT_MONITOR_PERIOD_SECONDS = 5
MONITOR_STOP_WAIT_MS = 1000

FILE_PANEL_WIDTH = theme.SIDE_PANEL_WIDTH

# The vendor export XML's macro_type for a plain "act as this key" remap --
# see re_notes/key_remap_macros.md's note that the XML's macro_type values are
# a separate local-DB vocabulary from the wire table's entry types, plus the
# cross-reference in this tab's docstring. It's the only macro_type
# KeyAssignmentDialog can produce, so it's the only one read/written here.
KEY_REMAP_MACRO_TYPE = "2"


def _keyboard_config_dir() -> pathlib.Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    save_dir = pathlib.Path(base) / "Keyboard_Config"
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir


def _next_config_name(save_dir: pathlib.Path) -> str:
    best = 0
    for path in save_dir.glob("KeyboardConfig*.xml"):
        digits = path.stem[len("KeyboardConfig"):]
        if digits.isdigit():
            best = max(best, int(digits))
    return f"KeyboardConfig{best + 1}"


def _load_keyboard_config_xml(path: pathlib.Path) -> tuple[dict[int, int], int]:
    """Parse a vendor `profile` file into {key_id: hid_usage}, plus a count of
    items skipped because they use a macro_type, fn_layer or modifier this
    app doesn't support producing yet (see re_notes/key_remap_macros.md) or
    name a key this keyboard doesn't have.
    """
    root = safe_ET.parse(path).getroot()
    if root.tag != "profile":
        raise ValueError(f"not a profile file (root is <{root.tag}>)")

    remaps: dict[int, int] = {}
    skipped = 0
    keyitems = root.find("keyitems")
    for item in [] if keyitems is None else keyitems.findall("item"):
        if (item.get("macro_type") != KEY_REMAP_MACRO_TYPE
                or item.get("fn_layer", "0") != "0"
                or item.get("macro_value2", "0") != "0"
                or item.get("macro_value3", "0") != "0"):
            skipped += 1
            continue
        try:
            key_code = int(item.get("key_code", "-1"))
            hid_usage = int(item.get("macro_value", "-1"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        key_id = key_layout.KEY_ID_BY_HID.get(key_code)
        if key_id is None or not 1 <= hid_usage <= 0xFF:
            skipped += 1
            continue
        remaps[key_id] = hid_usage
    return remaps, skipped


def _save_keyboard_config_xml(path: pathlib.Path, remaps: dict[int, int]) -> None:
    root = ET.Element("profile")
    ET.SubElement(root, "profileinfo", name=path.stem)
    keyitems = ET.SubElement(root, "keyitems")
    for key_id, hid_usage in remaps.items():
        ET.SubElement(
            keyitems,
            "item",
            fn_layer="0",
            key_code=str(key_layout.HID_BY_KEY_ID[key_id]),
            layout_value="0",
            layout_desc="",
            macro_type=KEY_REMAP_MACRO_TYPE,
            macro_value=str(hid_usage),
            macro_value2="0",
            macro_value3="0",
            macro_desc=kb_protocol.HID_USAGE_DISPLAY_NAMES.get(hid_usage, ""),
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class KeyboardTab(QWidget):
    busy_changed = Signal(bool)
    # (value, maximum) for whichever tab is hosting the button that started
    # the write -- the Config tab, since this one no longer has any controls
    # of its own to put a progress bar under.
    write_progress = Signal(int, int)
    # The system-monitor stream's running state, for MainWindow to pause
    # colour polling with (the way it does for a User Lighting animation).
    monitoring_changed = Signal(bool)
    # (cpu_load, gpu_load) of the monitor stream's most recent send, for the
    # Config tab's readout.
    monitor_loaded = Signal(int, int)

    def __init__(self, selector: DeviceSelector, debug_log: DebugLog) -> None:
        super().__init__()
        self._selector = selector
        self._debug_log = debug_log
        self._thread = None
        self._worker = None
        self._busy = False
        self._device_ready = False
        self._poll_worker = None
        self._poll_thread = None
        self._poll_busy = False
        self._external_busy = False
        self._pending_write = None
        self._monitor_worker = None
        self._monitor_thread = None
        self._monitoring = False
        self._monitor_period = settings.monitor_period_seconds()
        self._shutting_down = False
        # Every key assigned this session, key_id -> HID usage. The keyboard
        # itself can't be read back (see build_key_remap_transfer's
        # docstring), so this is the only record of "what's currently
        # assigned" -- every write resends the whole dict, and Save Current
        # saves it. Starts empty on every launch/tab creation.
        self._remaps: dict[int, int] = {}
        self._file_remaps: dict[int, int] | None = None

        self._build_ui()
        selector.changed.connect(self._on_device_changed)
        self._refresh_config_list()

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.addWidget(self._build_file_panel())

        controls = QVBoxLayout()
        overlay_row = QHBoxLayout()
        overlay_row.addStretch(1)
        overlay_row.addWidget(self._build_overlay())
        overlay_row.addStretch(1)
        controls.addLayout(overlay_row)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(DEFAULT_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_timer.start()

    def _build_overlay(self) -> KeyboardOverlay:
        overlay = KeyboardOverlay()
        overlay.setVisible(False)
        overlay.keyClicked.connect(self._on_key_clicked)
        self.overlay = overlay
        return overlay

    def _build_file_panel(self) -> QGroupBox:
        group = QGroupBox("Saved Keyboard Configs")
        group.setMaximumWidth(FILE_PANEL_WIDTH)
        layout = QVBoxLayout(group)

        self.config_list = QListWidget()
        self.config_list.currentItemChanged.connect(self._on_config_selected)
        layout.addWidget(self.config_list)

        self.apply_config_button = QPushButton("Apply to Keyboard")
        self.apply_config_button.clicked.connect(self._on_apply_config)
        self.apply_config_button.setEnabled(False)
        layout.addWidget(self.apply_config_button)

        save_button = QPushButton("Save Current")
        save_button.clicked.connect(self._on_save_current_config)
        layout.addWidget(save_button)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_config_list)
        layout.addWidget(refresh_button)

        return group

    # -- saved keyboard configs ---------------------------------------------

    def _refresh_config_list(self) -> None:
        self.config_list.clear()
        for path in sorted(_keyboard_config_dir().glob("*.xml"), key=lambda p: p.name.lower()):
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.config_list.addItem(item)

    def _on_config_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        # Selecting only loads and arms "Apply to Keyboard" -- nothing is
        # written until that button is pressed, same rule as Saved Lighting.
        self._file_remaps = None
        if current is not None:
            path = pathlib.Path(current.data(Qt.ItemDataRole.UserRole))
            try:
                remaps, skipped = _load_keyboard_config_xml(path)
            except (OSError, ValueError, ET.ParseError) as exc:
                self._debug_log.append("Keyboard", f"-- load {path.name} failed: {exc}")
                QMessageBox.critical(self, "Load Error", f"Could not read {path.name}:\n{exc}")
            else:
                self._file_remaps = remaps
                note = f" ({skipped} unsupported item(s) skipped)" if skipped else ""
                self._debug_log.append(
                    "Keyboard", f"-- loaded {path.name}: {len(remaps)} key(s){note}"
                )
        self.apply_config_button.setEnabled(self._file_remaps is not None)

    def _on_apply_config(self) -> None:
        if self._file_remaps is None:
            return
        self._remaps = dict(self._file_remaps)
        self._write_remaps()

    def _on_save_current_config(self) -> None:
        save_dir = _keyboard_config_dir()
        name, accepted = QInputDialog.getText(
            self, "Save Keyboard Config", "Name:", text=_next_config_name(save_dir)
        )
        name = name.strip()
        if not accepted or not name:
            return

        path = save_dir / f"{name}.xml"
        if path.exists():
            confirm = QMessageBox.question(
                self, "Save Keyboard Config", f"{path.name} already exists. Overwrite it?"
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        try:
            _save_keyboard_config_xml(path, self._remaps)
        except OSError as exc:
            self._debug_log.append("Keyboard", f"-- save {path.name} failed: {exc}")
            QMessageBox.critical(self, "Save Error", f"Could not write {path.name}:\n{exc}")
            return

        self._debug_log.append("Keyboard", f"-- saved {path.name}")
        self._refresh_config_list()
        for row in range(self.config_list.count()):
            if self.config_list.item(row).text() == path.stem:
                self.config_list.setCurrentRow(row)
                break

    # -- key assignment ------------------------------------------------------

    def _on_key_clicked(self, key_id: int) -> None:
        """A left-click on an overlay key: open its assignment dialog and, on
        Apply, write the remap through the usual transaction path. -1 means
        the click deselected the already-selected key instead (the overlay's
        toggle), which opens nothing."""
        if key_id < 0 or not self._device_ready or self._busy or self._monitoring:
            return
        usage = key_layout.HID_BY_KEY_ID.get(key_id)
        # The layout XML's names are keycap legends ("!1", ".>", "SCROOL");
        # prefer the HID name for the dialog title where one exists.
        key_name = (kb_protocol.HID_USAGE_DISPLAY_NAMES.get(usage)
                    or key_layout.KEY_RECTS[key_id].name)
        dialog = KeyAssignmentDialog(key_name, self)
        if not dialog.exec():
            return
        self._remaps[key_id] = dialog.hid_usage
        self._write_remaps()

    def _write_remaps(self) -> None:
        """Send every remap assigned so far as one write -- build_key_remap_
        blocks rewrites the whole table regardless, so this is what makes an
        earlier click's remap survive a later one instead of being reset by
        it."""
        self._run_transactions(
            kb_protocol.build_key_remap_transfer_all(self._remaps))

    # -- device handling --------------------------------------------------

    def _on_device_changed(self, status: str, enabled: bool) -> None:
        self._device_ready = enabled
        self.overlay.setVisible(enabled)
        if not enabled:
            self.overlay.clear_swatches()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    def set_external_busy(self, busy: bool) -> None:
        """Called by MainWindow with whether *any* tab is mid-upload -- colour
        polling pauses for those too, not just this tab's own actions, since
        any of them can be holding the keyboard's hidraw handle open."""
        self._external_busy = busy

    # -- actions ------------------------------------------------------------

    def set_clock_now(self) -> None:
        """Set the keyboard's onboard RTC to the host's current time. Called
        from the Config tab's button."""
        self._run_transactions(kb_protocol.build_rtc_transfer(datetime.now()))

    def set_poll_interval(self, interval_ms: int) -> None:
        """Retune colour polling live, from the Config tab's spin box."""
        self._poll_timer.setInterval(interval_ms)

    def set_monitor_period(self, seconds: int) -> None:
        """Retune the system-monitor send cadence, from the Config tab's spin
        box. Applies live to a running stream via the worker's own
        set_period(); otherwise just takes effect on the next Start."""
        self._monitor_period = seconds
        if self._monitoring and self._monitor_worker is not None:
            self._monitor_worker.set_period(seconds)

    def set_settings(self, response_time: int, sleep_time: int) -> None:
        """Write the settings panel (response-time level and sleep-time
        value), from the Config tab's dropdowns. The write carries both
        slots, as the vendor app's does."""
        self._run_transactions(
            kb_protocol.build_settings_transfer(sleep_time, response_time))

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _run_transactions(self, transactions: list) -> None:
        if self._busy or self._monitoring:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Keyboard", "No device selected.")
            return

        self._set_busy(True)
        self.write_progress.emit(0, max(len(transactions), 1))
        self._debug_log.clear()

        if self._poll_busy:
            # A colour-poll read already has the hidraw handle open --
            # opening a second one for this write at the same time is exactly
            # the interleaving _on_poll_tick's own guard exists to prevent.
            # Queue it; _on_poll_thread_stopped starts it once that read
            # actually finishes, typically well under a poll interval later.
            self._pending_write = (device_path, transactions)
            return
        self._start_write(device_path, transactions)

    def _start_write(self, device_path: str, transactions: list) -> None:
        # See lighting_tab.py's _run_transactions for why `_worker`/`_thread`
        # are kept referenced until `thread.finished` (not `worker.finished`)
        # and why `_busy` is only cleared there.
        self._worker = KeyboardWorker(device_path, transactions)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._on_thread_stopped)

    def _on_progress(self, index: int, total: int, name: str, acked: bool) -> None:
        self.write_progress.emit(index + 1, total)
        self._debug_log.append("Keyboard", f"{name}: {'ok' if acked else 'NOT ACKED'}")

    def _on_finished(self, success: bool, message: str) -> None:
        self._debug_log.append("Keyboard", f"-- {message}")
        if not success:
            text = message
            if "permission" in message.lower():
                text = f"{message}\n\n{KEYBOARD_PERMISSION_HINT}"
            QMessageBox.critical(self, "Keyboard Error", text)

    def _on_thread_stopped(self) -> None:
        # Only safe to allow a new action (and thus a new
        # self._worker/self._thread reassignment) once the QThread has
        # actually stopped -- not merely once the worker reported it was
        # done, which races the still-shutting-down old thread.
        self._set_busy(False)

    # -- system-monitor stream ---------------------------------------------

    @property
    def is_monitoring(self) -> bool:
        return self._monitoring

    def set_monitoring(self, enabled: bool) -> None:
        """Start or stop the touchscreen's CPU/GPU load stream, driven by the
        Config tab's toggle. Not "busy" in the _busy sense: like a User
        Lighting animation it runs indefinitely, so it must not raise the
        loading overlay or block closing -- it only pauses colour polling.
        """
        if enabled:
            self._start_monitor_stream()
        else:
            self._stop_monitor_stream()

    def _start_monitor_stream(self) -> None:
        if self._monitoring or self._busy:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Keyboard", "No device selected.")
            return

        # The sampler is created up front on the GUI thread and handed to the
        # worker, which runs it on its own thread; it keeps only its own
        # /proc/stat deltas as state, so sharing it across the two threads is
        # safe (the worker is the only one calling it).
        self._monitor_worker = MonitorStreamWorker(
            device_path, MonitorSampler(), period=self._monitor_period)
        self._monitor_worker.finished.connect(self._on_monitor_finished)
        self._monitor_worker.sent.connect(self.monitor_loaded)
        self._monitor_worker.sent.connect(self._on_monitor_sent)
        self._monitor_thread = start_worker(self._monitor_worker)
        self._set_monitoring(True)
        self._debug_log.append(
            "Keyboard", f"-- streaming CPU/GPU load every {self._monitor_period:g}s")

    def _on_monitor_sent(self, cpu_load: int, gpu_load: int) -> None:
        self._debug_log.append(
            "Keyboard", f"-- polled: CPU {cpu_load}% · GPU {gpu_load}%")

    def _stop_monitor_stream(self) -> None:
        """Stop the stream and wait for its thread, so the device is free
        before whatever comes next opens it. A no-op when nothing is running.

        Blocking the GUI thread here is deliberate: the wait is at most ~50ms
        after the current send (the worker slices its inter-send sleep), and
        every alternative means threading a continuation through every caller
        for a delay too short to see.
        """
        if not self._monitoring:
            return
        self._monitor_worker.stop()
        if self._monitor_thread is not None:
            self._monitor_thread.wait(MONITOR_STOP_WAIT_MS)
        # During shutdown the saved toggle state must survive the stop (a
        # graceful quit should leave "running" so the next run resumes it),
        # so don't emit monitoring_changed here.
        if not self._shutting_down:
            self._set_monitoring(False)

    def _on_monitor_finished(self, success: bool, message: str) -> None:
        # Fires on a clean stop too, so _set_monitoring's `if monitoring ==
        # self._monitoring: return` keeps the toggle state right whichever way
        # the stream ended. Skipped entirely during shutdown: nothing left to
        # update, and no dialogs when the window is already going away.
        if self._shutting_down:
            return
        self._debug_log.append("Keyboard", f"-- {message}")
        self._set_monitoring(False)
        if not success:
            text = message
            if "permission" in message.lower():
                text = f"{message}\n\n{KEYBOARD_PERMISSION_HINT}"
            QMessageBox.critical(self, "Keyboard Error", text)

    def _set_monitoring(self, monitoring: bool) -> None:
        if monitoring == self._monitoring:
            return
        self._monitoring = monitoring
        self.monitoring_changed.emit(monitoring)

    # -- colour polling -----------------------------------------------------

    def _on_poll_tick(self) -> None:
        # Skipped (not queued) while busy -- an RTC write and a colour read
        # opening the same hidraw node from two threads at once could
        # interleave the firmware's stateful begin/commit/end session.
        # `_poll_busy` guards against a slow read still being in flight when
        # the next tick fires, rather than piling up overlapping workers.
        if not self._device_ready or self._busy or self._external_busy or self._poll_busy:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            return

        self._poll_busy = True
        self._poll_worker = CallableResultWorker(lambda: read_colors(device_path))
        self._poll_worker.finished.connect(self._on_poll_finished)
        self._poll_thread = start_worker(self._poll_worker)
        self._poll_thread.finished.connect(self._on_poll_thread_stopped)

    def _on_poll_finished(self, colors: object, error: str) -> None:
        # Silently skipped on error -- a transient read failure every second
        # shouldn't spam a dialog; explicit actions (Set Clock) still surface
        # their own errors.
        if not error:
            self.overlay.set_swatches(colors)

    def _on_poll_thread_stopped(self) -> None:
        self._poll_busy = False
        if self._pending_write is not None:
            device_path, transactions = self._pending_write
            self._pending_write = None
            self._start_write(device_path, transactions)

    def shutdown(self) -> None:
        """Called by MainWindow just before the app closes. Colour polling
        isn't gated by MainWindow.closeEvent's busy-check (it's a lightweight,
        frequent read, not a risky write worth nagging the user to wait out)
        -- but an in-flight poll's QThread still has to actually stop before
        this object graph gets torn down, or Qt aborts the process rather
        than destroy a thread that's still running. `_poll_busy` guards
        touching `_poll_thread` at all: once it's False, `_on_poll_thread_stopped`
        has already run, meaning `thread.finished` (and the deleteLater()
        chained off the same signal in workers.start_worker) has already
        fired, so the underlying C++ QThread may no longer exist to call
        into."""
        self._poll_timer.stop()
        self._shutting_down = True
        self._stop_monitor_stream()
        if self._poll_busy and self._poll_thread is not None:
            self._poll_thread.quit()
            self._poll_thread.wait()
