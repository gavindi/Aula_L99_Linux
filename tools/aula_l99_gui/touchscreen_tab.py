"""Touchscreen (aula_l99_screen) control tab: image upload + GIF upload."""
from __future__ import annotations

import csv
import io
import pathlib
import shutil
import subprocess

from PySide6.QtCore import QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QDoubleSpinBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

try:
    from PIL import Image, ImageSequence
except ImportError:  # pragma: no cover - Pillow is a declared dependency
    Image = None
    ImageSequence = None

from aula_l99_screen import protocol as screen_protocol

from .debug_log import DebugLog
from .device_tab import DeviceSelector
from .device_utils import SCREEN_PERMISSION_HINT
from .workers import CallableResultWorker, ScreenUploadWorker, start_worker

DEFAULT_GIF_DELAY = 50
DEFAULT_PACKET_GAP_MS = 0.0
THUMBNAIL_ICON_SIZE = QSize(96, 144)
STRIP_ICON_SIZE = QSize(64, 96)
PREVIEW_ICON_SIZE = QSize(200, 300)  # same 2:3 aspect as the panel (320x480)
SOURCE_IMAGE_FILTER = "Supported files (*.png *.jpg *.jpeg *.gif *.mp4)"
SINGLE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def _pillow_missing_message() -> str:
    return "Pillow is required to load images (pip install pillow)."


def _animation_save_dir() -> pathlib.Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    save_dir = pathlib.Path(base) / "Customized_Animation"
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir


def _next_animation_path(save_dir: pathlib.Path) -> pathlib.Path:
    best = 0
    for path in save_dir.iterdir():
        if path.is_file() and path.stem.isdigit():
            best = max(best, int(path.stem))
    return save_dir / f"{best + 1}.gif"


def _save_frames_as_gif(
    frames: list[list[tuple[int, int, int]]], delay: int, path: pathlib.Path
) -> None:
    width, height = screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT
    images = []
    for pixels in frames:
        image = Image.new("RGB", (width, height))
        image.putdata(pixels)
        images.append(image)
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=delay * 10,
        loop=0,
    )


def _save_animation_config(
    csv_path: pathlib.Path, output_name: str, source_paths: list[str], delay: int | None
) -> None:
    # Source paths are written out in full (not just basename) so the
    # thumbnail strip can reopen the original files later -- their directory
    # isn't otherwise recoverable, unlike the output file which always sits
    # alongside this csv. delay is None for a single-image save, where the
    # column is meaningless -- written blank rather than a placeholder value.
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow([output_name])
        for source_path in source_paths:
            writer.writerow([source_path, "" if delay is None else delay])


class TouchscreenTab(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, selector: DeviceSelector, debug_log: DebugLog) -> None:
        super().__init__()
        self._selector = selector
        self._debug_log = debug_log
        self._thread = None
        self._worker = None
        self._convert_thread = None
        self._convert_worker = None
        self._convert_result: tuple[list[bytes], int, int] | None = None
        self._convert_error = ""
        self._local_save_path: pathlib.Path | None = None
        self._local_save_error: str | None = None
        self._pending_upload_device_path: str | None = None
        self._busy = False
        self._device_ready = False
        self._action_buttons: list[QPushButton] = []

        self._build_source_paths: list[str] = []

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.addWidget(self._build_thumbnail_column())

        right = QVBoxLayout()
        right.addWidget(self._build_source_strip())
        right.addWidget(self._build_send_to_device_group())
        right.addWidget(self._build_gif_group())

        self.progress_bar = QProgressBar()
        right.addWidget(self.progress_bar)
        right.addStretch(1)

        outer.addLayout(right, 1)

        self._refresh_thumbnails()
        self._sync_actions()

    def _build_thumbnail_column(self) -> QGroupBox:
        group = QGroupBox("Saved Animations")
        group.setFixedWidth(240)
        layout = QVBoxLayout(group)

        buttons_row = QHBoxLayout()
        self.new_animation_button = QPushButton("New")
        self.new_animation_button.clicked.connect(self._on_new_animation)
        buttons_row.addWidget(self.new_animation_button)
        self.delete_animation_button = QPushButton("Delete")
        self.delete_animation_button.clicked.connect(self._on_delete_animation)
        buttons_row.addWidget(self.delete_animation_button)
        layout.addLayout(buttons_row)

        self.thumbnail_list = QListWidget()
        self.thumbnail_list.setIconSize(THUMBNAIL_ICON_SIZE)
        self.thumbnail_list.currentItemChanged.connect(self._on_saved_animation_selected)
        layout.addWidget(self.thumbnail_list)

        return group

    def _build_source_strip(self) -> QGroupBox:
        group = QGroupBox("Source Images")
        layout = QVBoxLayout(group)

        choose_button = QPushButton("Choose Image…")
        choose_button.clicked.connect(self._on_choose_source_images)
        layout.addWidget(choose_button)

        self.source_strip = QListWidget()
        self.source_strip.setViewMode(QListWidget.ViewMode.IconMode)
        self.source_strip.setFlow(QListWidget.Flow.LeftToRight)
        self.source_strip.setWrapping(False)
        self.source_strip.setMovement(QListWidget.Movement.Static)
        self.source_strip.setIconSize(STRIP_ICON_SIZE)
        self.source_strip.setFixedHeight(STRIP_ICON_SIZE.height() + 30)
        self.source_strip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.source_strip.customContextMenuRequested.connect(self._on_source_strip_context_menu)
        self.source_strip.currentItemChanged.connect(self._on_source_image_selected)
        layout.addWidget(self.source_strip)

        self.source_preview = QLabel("(no image selected)")
        self.source_preview.setObjectName("ImagePreview")
        self.source_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_preview.setFixedSize(PREVIEW_ICON_SIZE)
        layout.addWidget(self.source_preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        return group

    def _refresh_thumbnails(self) -> None:
        self.thumbnail_list.clear()
        self.source_strip.clear()
        if Image is None:
            return
        save_dir = _animation_save_dir()
        csv_paths = sorted(
            (p for p in save_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"
             and p.stem.isdigit()),
            key=lambda p: int(p.stem),
            reverse=True,
        )
        for csv_path in csv_paths:
            item = QListWidgetItem(QIcon(self._load_animation_thumbnail(csv_path)), csv_path.stem)
            item.setData(Qt.ItemDataRole.UserRole, csv_path)
            self.thumbnail_list.addItem(item)
        self._sync_list_buttons()

    def _load_animation_thumbnail(self, csv_path: pathlib.Path) -> QPixmap:
        # Covers a freshly-"New"-ed placeholder (empty csv, no gif yet) as
        # well as a genuinely corrupt/unreadable save -- both fall back to a
        # blank tile rather than being silently skipped from the list.
        try:
            with csv_path.open(newline="") as fh:
                rows = list(csv.reader(fh))
            gif_path = csv_path.with_name(rows[0][0])
            with Image.open(gif_path) as im:
                pixmap = self._to_pixmap(im.convert("RGB"))
        except Exception:  # noqa: BLE001
            pixmap = QPixmap(THUMBNAIL_ICON_SIZE)
            pixmap.fill(Qt.GlobalColor.darkGray)
            return pixmap
        return pixmap.scaled(
            THUMBNAIL_ICON_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _select_animation(self, csv_path: pathlib.Path) -> None:
        for i in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == csv_path:
                self.thumbnail_list.setCurrentItem(item)
                return

    def _current_save_target(self) -> pathlib.Path:
        # Base path (no extension) the next Send To save should write to:
        # whatever's currently selected in Saved Animations, so a save
        # updates that entry in place -- or a freshly auto-incremented
        # number if nothing's selected. GUI-thread only (reads a widget).
        item = self.thumbnail_list.currentItem()
        if item is not None:
            csv_path = item.data(Qt.ItemDataRole.UserRole)
            return csv_path.with_suffix("")
        return _next_animation_path(_animation_save_dir()).with_suffix("")

    def _sync_list_buttons(self) -> None:
        # New/Delete are local file-management actions, not device I/O, so
        # unlike _action_buttons they stay enabled without a device attached
        # -- only gated on `_busy` (avoids racing a reserved/in-flight save)
        # and, for Delete, on something actually being selected.
        self.new_animation_button.setEnabled(not self._busy)
        self.delete_animation_button.setEnabled(
            not self._busy and self.thumbnail_list.currentItem() is not None
        )

    def _on_new_animation(self) -> None:
        if self._busy:
            return
        csv_path = _next_animation_path(_animation_save_dir()).with_suffix(".csv")
        try:
            csv_path.touch()
        except OSError as exc:
            QMessageBox.critical(self, "Screen", f"Could not create {csv_path}:\n{exc}")
            return
        self._refresh_thumbnails()
        self._select_animation(csv_path)

    def _on_delete_animation(self) -> None:
        if self._busy:
            return
        item = self.thumbnail_list.currentItem()
        if item is None:
            return
        csv_path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Screen",
            f"Delete saved animation \"{csv_path.stem}\"? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        csv_path.unlink(missing_ok=True)
        # The companion output is a .gif for an animation or a .png for a
        # single-image send -- try both, harmless if one doesn't exist.
        csv_path.with_suffix(".gif").unlink(missing_ok=True)
        csv_path.with_suffix(".png").unlink(missing_ok=True)
        self._refresh_thumbnails()

    def _on_saved_animation_selected(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        # Selecting a save loads its sources into the *live, editable* build
        # list -- the same list "Choose Image" appends to -- so browsing
        # history doubles as loading a starting point to keep editing. When
        # nothing is selected (including the just-deleted item losing its
        # selection) the build list resets to empty rather than left stale.
        self._sync_list_buttons()
        if current is None:
            self._build_source_paths = []
            self._refresh_source_strip()
            return
        csv_path = current.data(Qt.ItemDataRole.UserRole)
        try:
            with csv_path.open(newline="") as fh:
                rows = list(csv.reader(fh))
        except OSError:
            return
        self._build_source_paths = [row[0] for row in rows[1:] if row]
        self._refresh_source_strip()

    def _refresh_source_strip(self) -> None:
        self.source_strip.clear()
        if Image is None:
            return
        for source_path in self._build_source_paths:
            pixmap = self._load_source_thumbnail(source_path)
            item = QListWidgetItem(QIcon(pixmap), "")
            item.setToolTip(source_path)
            item.setData(Qt.ItemDataRole.UserRole, source_path)
            self.source_strip.addItem(item)
        self._sync_send_buttons()

    def _load_source_thumbnail(self, path: str, size: QSize = STRIP_ICON_SIZE) -> QPixmap:
        pixmap = None
        try:
            with Image.open(path) as im:
                pixmap = self._to_pixmap(im.convert("RGB"))
        except Exception:  # noqa: BLE001 - not Pillow-openable, e.g. .mp4
            pass
        if pixmap is None and pathlib.Path(path).suffix.lower() == ".mp4":
            frame = self._video_thumbnail_frame(path)
            if frame is not None:
                pixmap = self._to_pixmap(frame)
        if pixmap is None:
            pixmap = QPixmap(size)
            pixmap.fill(Qt.GlobalColor.darkGray)
            return pixmap
        return pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _video_thumbnail_frame(self, path: str):
        # Best-effort only: a thumbnail failure should fall back to the grey
        # placeholder tile, never raise/crash the UI -- unlike
        # _extract_video_frames, which raises since it feeds an actual upload.
        if shutil.which("ffmpeg") is None:
            return None
        command = [
            "ffmpeg", "-i", path, "-vframes", "1",
            "-f", "image2pipe", "-vcodec", "png", "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=True)
            return Image.open(io.BytesIO(result.stdout)).convert("RGB")
        except Exception:  # noqa: BLE001
            return None

    def _on_source_image_selected(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.source_preview.setPixmap(QPixmap())
            self.source_preview.setText("(no image selected)")
            return
        source_path = current.data(Qt.ItemDataRole.UserRole)
        self.source_preview.setPixmap(self._load_source_thumbnail(source_path, PREVIEW_ICON_SIZE))
        self.source_preview.setText("")

    def _on_choose_source_images(self) -> None:
        if Image is None:
            QMessageBox.critical(self, "Screen", _pillow_missing_message())
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose Source Images", filter=SOURCE_IMAGE_FILTER
        )
        if not paths:
            return
        self._build_source_paths.extend(paths)
        self._refresh_source_strip()

    def _on_source_strip_context_menu(self, pos) -> None:
        item = self.source_strip.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        remove_action = menu.addAction("Remove")
        if menu.exec(self.source_strip.mapToGlobal(pos)) != remove_action:
            return
        # By index (not value) so a duplicate path is removed at the row
        # actually clicked, not always the first matching occurrence.
        index = self.source_strip.row(item)
        del self._build_source_paths[index]
        self._refresh_source_strip()

    def _build_send_to_device_group(self) -> QGroupBox:
        group = QGroupBox("Send to Device")
        layout = QHBoxLayout(group)

        self.background_button = QPushButton("Background")
        self.background_button.clicked.connect(
            lambda: self._on_send_single_image(screen_protocol.BACKGROUND_FLASH_BASE)
        )
        layout.addWidget(self.background_button)

        self.photo_frame_button = QPushButton("Photo Frame")
        self.photo_frame_button.clicked.connect(
            lambda: self._on_send_single_image(screen_protocol.PHOTO_FRAME_FLASH_BASE)
        )
        layout.addWidget(self.photo_frame_button)

        self.customized_animation_button = QPushButton("Customized Animation")
        self.customized_animation_button.clicked.connect(self._on_upload_gif)
        layout.addWidget(self.customized_animation_button)

        layout.addStretch(1)
        layout.addWidget(QLabel("Packet gap (ms):"))
        self.packet_gap_spin = QDoubleSpinBox()
        self.packet_gap_spin.setRange(0.0, 50.0)
        self.packet_gap_spin.setSingleStep(0.5)
        self.packet_gap_spin.setDecimals(1)
        self.packet_gap_spin.setValue(DEFAULT_PACKET_GAP_MS)
        self.packet_gap_spin.setToolTip(
            "Delay after each packet during upload. Lower is faster but "
            "unverified against the panel's firmware -- if transfers start "
            "failing, raise this back up."
        )
        layout.addWidget(self.packet_gap_spin)

        return group

    def _build_gif_group(self) -> QGroupBox:
        group = QGroupBox("Animation Settings")
        layout = QVBoxLayout(group)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Delay (centiseconds):"))
        self.gif_delay_spin = QSpinBox()
        self.gif_delay_spin.setRange(1, 1000)
        self.gif_delay_spin.setValue(DEFAULT_GIF_DELAY)
        settings_row.addWidget(self.gif_delay_spin)
        self.dither_checkbox = QCheckBox("Dither")
        self.dither_checkbox.setChecked(True)
        settings_row.addWidget(self.dither_checkbox)
        settings_row.addStretch(1)
        layout.addLayout(settings_row)

        return group

    # -- device handling --------------------------------------------------

    def _on_device_changed(self, status: str, enabled: bool) -> None:
        self._device_ready = enabled
        self._sync_actions()

    def _sync_actions(self) -> None:
        # Gating on `_busy` as well as device availability matters because the
        # Device tab's Refresh stays clickable during an upload -- without it,
        # a mid-upload refresh would re-arm these buttons.
        enabled = self._device_ready and not self._busy
        for button in self._action_buttons:
            button.setEnabled(enabled)
        self._sync_send_buttons()

    def _sync_send_buttons(self) -> None:
        # These need extra conditions (content of `_build_source_paths`) on
        # top of the usual device-ready/not-busy gating, so they're kept out
        # of `_action_buttons` and synced here instead -- called both when
        # busy/device-ready changes (_sync_actions) and whenever the source
        # list's contents change (_refresh_source_strip).
        base_enabled = self._device_ready and not self._busy
        single_image = (
            len(self._build_source_paths) == 1
            and pathlib.Path(self._build_source_paths[0]).suffix.lower() in SINGLE_IMAGE_SUFFIXES
        )
        self.background_button.setEnabled(base_enabled and single_image)
        self.photo_frame_button.setEnabled(base_enabled and single_image)
        self.customized_animation_button.setEnabled(
            base_enabled and len(self._build_source_paths) >= 1
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
        self._sync_actions()
        self._sync_list_buttons()

    # -- image loading ------------------------------------------------------

    def _load_image(self, path: str):
        image = Image.open(path)
        image = image.convert("RGB")
        size = (screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT)
        if image.size != size:
            image = image.resize(size, Image.LANCZOS)
        return image

    def _pixels_from_image(self, image) -> list[tuple[int, int, int]]:
        if hasattr(image, "get_flattened_data"):
            return list(image.get_flattened_data())
        return list(image.getdata())

    def _to_pixmap(self, image) -> QPixmap:
        data = image.tobytes("raw", "RGB")
        qimage = QImage(
            data, image.width, image.height, image.width * 3,
            QImage.Format.Format_RGB888,
        )
        return QPixmap.fromImage(qimage.copy())

    # -- single image upload --------------------------------------------

    def _on_send_single_image(self, address: int) -> None:
        if self._busy or len(self._build_source_paths) != 1:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Screen", "No device selected.")
            return
        path = self._build_source_paths[0]
        try:
            image = self._load_image(path)
        except OSError as exc:
            QMessageBox.critical(self, "Screen", f"Could not open {path}:\n{exc}")
            return

        try:
            save_path = self._current_save_target().with_suffix(".png")
            image.save(save_path)
            _save_animation_config(save_path.with_suffix(".csv"), save_path.name, [path], None)
            self._local_save_path = save_path
            self._local_save_error = None
        except Exception as exc:  # must not abort the upload over a backup failure
            self._local_save_path = None
            self._local_save_error = str(exc)

        if self._local_save_error:
            self._debug_log.append("Touchscreen", f"Local copy not saved: {self._local_save_error}")
        else:
            self._debug_log.append("Touchscreen", f"Saved local copy: {self._local_save_path}")
            self._refresh_thumbnails()
            self._select_animation(self._local_save_path.with_suffix(".csv"))

        blob = screen_protocol.build_image_file(
            image.tobytes(), screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT
        )
        packets = screen_protocol.build_upload(blob, address)
        self._start_upload(device_path, packets)

    # -- GIF source selection ------------------------------------------

    def _current_gif_source_paths(self) -> list[str]:
        return list(self._build_source_paths)

    def _frames_from_gif(self, path: str) -> list[list[tuple[int, int, int]]]:
        frames = []
        size = (screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT)
        with Image.open(path) as im:
            for frame in ImageSequence.Iterator(im):
                rgb = frame.convert("RGB")
                if rgb.size != size:
                    rgb = rgb.resize(size, Image.LANCZOS)
                frames.append(self._pixels_from_image(rgb))
        if not frames:
            raise ValueError(f"{path} has no frames.")
        return frames

    def _collect_gif_frame_pixels(self, delay: int) -> list[list[tuple[int, int, int]]]:
        # Raises rather than showing a QMessageBox and returning None: this
        # runs off the GUI thread now (see _build_gif_packets), and Qt
        # widgets aren't thread-safe. _on_convert_thread_stopped turns the
        # exception message into a dialog back on the GUI thread once the
        # background job (a CallableResultWorker) finishes.
        if not self._build_source_paths:
            raise ValueError("No source images selected.")
        frames: list[list[tuple[int, int, int]]] = []
        for path in self._build_source_paths:
            suffix = pathlib.Path(path).suffix.lower()
            if suffix == ".mp4":
                frames.extend(self._extract_video_frames(path, delay))
            elif suffix == ".gif":
                frames.extend(self._frames_from_gif(path))
            else:
                try:
                    frames.append(self._pixels_from_image(self._load_image(path)))
                except OSError as exc:
                    raise ValueError(f"Could not open {path}: {exc}") from exc
        return frames

    def _extract_video_frames(self, path: str, delay: int) -> list[list[tuple[int, int, int]]]:
        """Decodes video frames via a system ffmpeg subprocess -- no video
        decoding library is otherwise a dependency of this project, and
        shelling out avoids adding one (PyAV/opencv-python) just for this.

        Samples at fps = 100/delay so the extracted frame count matches the
        same "Delay (centiseconds)" spinbox every other source uses for
        playback timing, rather than pulling every frame of what's typically
        a 24-60fps source into what's a small, slow panel to redraw.
        """
        if shutil.which("ffmpeg") is None:
            raise ValueError(
                "ffmpeg is required to convert video and wasn't found on PATH. "
                "Install it (e.g. apt install ffmpeg) and try again."
            )

        width, height = screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT
        fps = 100.0 / delay
        command = [
            "ffmpeg", "-i", path,
            "-vf",
            f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace")
            raise ValueError(f"ffmpeg failed to decode {path}:\n{stderr[-800:]}") from exc

        frame_size = width * height * 3
        data = result.stdout
        # Drop a truncated trailing frame rather than fail outright -- ffmpeg
        # occasionally writes a partial last frame for an odd frame count.
        usable = len(data) - (len(data) % frame_size)
        frames = []
        for offset in range(0, usable, frame_size):
            chunk = data[offset:offset + frame_size]
            # zip over three byte-strided slices (each a C-level slice, not a
            # per-pixel Python loop) is the same reshape dither_frame_floyd_
            # steinberg's per-pixel loop can't avoid -- see protocol.py's
            # comment on that one for why a hot pure-Python loop here would
            # matter even off the GUI thread.
            frames.append(list(zip(chunk[0::3], chunk[1::3], chunk[2::3])))
        if not frames:
            raise ValueError("That video produced no frames.")
        return frames

    def _ensure_safe_colors(self, frames: list[list[tuple[int, int, int]]]) -> None:
        bad: dict[tuple[int, int, int], int] = {}
        for pixels in frames:
            for color in pixels:
                if not screen_protocol.is_safe_gif_color(*color):
                    bad[color] = bad.get(color, 0) + 1
        if bad:
            worst = sorted(bad.items(), key=lambda kv: -kv[1])[:10]
            lines = "\n".join(f"  rgb{color}: {count} px" for color, count in worst)
            raise ValueError(
                "These colors need dithering, which isn't supported -- every pixel "
                "must have R, G, or B at exactly 0 or 255. Check \"Dither\" to "
                "encode this anyway (confirmed working on real hardware):\n\n" + lines
            )

    def _build_gif_packets(
        self, dither: bool, delay: int, save_path: pathlib.Path
    ) -> tuple[list[bytes], int, int]:
        """Everything slow about a GIF upload: decode/resize every source
        frame, then protocol.py's dithering + CRC computation. Runs on a
        background thread (see _on_upload_gif) -- profiled at ~3s for just a
        10-frame dithered GIF, which is long enough to freeze the window if
        run inline with the button click, as it used to be. `save_path` is
        resolved on the GUI thread beforehand (it reads a widget via
        _current_save_target, which isn't safe to touch from here).
        """
        frames = self._collect_gif_frame_pixels(delay)
        if not dither:
            self._ensure_safe_colors(frames)

        try:
            _save_frames_as_gif(frames, delay, save_path)
            _save_animation_config(
                save_path.with_suffix(".csv"), save_path.name,
                self._current_gif_source_paths(), delay,
            )
            self._local_save_path = save_path
            self._local_save_error = None
        except Exception as exc:  # must not abort the upload over a backup failure
            self._local_save_path = None
            self._local_save_error = str(exc)

        blob = screen_protocol.build_gif_blob(
            frames, screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT,
            delay=delay, dither=dither,
        )
        packets = screen_protocol.build_upload(blob, screen_protocol.GIF_FLASH_BASE)
        return packets, len(frames), len(blob)

    def _on_upload_gif(self) -> None:
        if self._busy:
            return
        if Image is None:
            QMessageBox.critical(self, "Screen", _pillow_missing_message())
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Screen", "No device selected.")
            return

        dither = self.dither_checkbox.isChecked()
        delay = self.gif_delay_spin.value()
        save_path = self._current_save_target().with_suffix(".gif")

        self._set_busy(True)
        self._debug_log.clear()
        self._debug_log.append("Touchscreen", "Converting frames…")

        # Separate worker/thread attributes from the upload phase's
        # (self._worker/self._thread, set in _start_upload) -- both are
        # reassigned on their own schedule and would otherwise race each
        # other's "only safe once the old QThread has actually stopped" rule.
        self._pending_upload_device_path = device_path
        self._convert_worker = CallableResultWorker(
            lambda: self._build_gif_packets(dither, delay, save_path)
        )
        self._convert_worker.finished.connect(self._on_gif_converted)
        self._convert_thread = start_worker(self._convert_worker)
        self._convert_thread.finished.connect(self._on_convert_thread_stopped)

    def _on_gif_converted(self, result: object, error: str) -> None:
        # Just stash the outcome -- see _on_convert_thread_stopped for why
        # `_busy` isn't touched and the next phase isn't started here.
        self._convert_result = result
        self._convert_error = error

    def _on_convert_thread_stopped(self) -> None:
        # Only safe to clear `_busy` (on failure) or start the next phase (on
        # success) once this QThread has actually stopped -- not merely once
        # the worker reported it was done, which races the still-shutting-down
        # old thread. Same reasoning as _on_thread_stopped below, for the
        # conversion phase's own worker/thread pair.
        if self._convert_error:
            self._set_busy(False)
            QMessageBox.critical(self, "Screen", self._convert_error)
            return
        packets, frame_count, blob_len = self._convert_result
        self._debug_log.append("Touchscreen", f"{frame_count} frame(s), {blob_len} bytes")
        if self._local_save_error:
            self._debug_log.append("Touchscreen", f"Local copy not saved: {self._local_save_error}")
        else:
            self._debug_log.append("Touchscreen", f"Saved local copy: {self._local_save_path}")
            self._refresh_thumbnails()
            self._select_animation(self._local_save_path.with_suffix(".csv"))
        # _busy stays True -- _start_upload sets it again (harmless) and it
        # only ever meant "an upload-tab action is in flight", covering both
        # the conversion and the upload phase.
        self._start_upload(self._pending_upload_device_path, packets)

    # -- shared upload plumbing ------------------------------------------

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _start_upload(self, device_path: str, packets: list[bytes]) -> None:
        self._set_busy(True)
        self.progress_bar.setMaximum(max(len(packets), 1))
        self.progress_bar.setValue(0)

        # `self._worker`/`self._thread` are reassigned (not cleared) here on
        # every run: they must stay referenced for as long as the previous
        # operation's QThread might still be alive. Both objects use
        # deleteLater() (see workers.start_worker) so the C++ side is
        # already torn down safely by the time this reassignment drops the
        # old Python reference -- explicitly nulling them from a slot
        # connected to their own finished signal raced with that deferred
        # deletion and crashed (double free). Reassignment itself is only
        # safe once the *old* QThread has actually stopped, which is why
        # `self._busy` (guarding re-entry into this method) is cleared from
        # `thread.finished`, not `worker.finished` -- see _on_thread_stopped.
        self._worker = ScreenUploadWorker(
            device_path, packets, gap=self.packet_gap_spin.value() / 1000.0
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._on_thread_stopped)

    def _on_progress(self, sent: int, total: int, acked: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(sent)
        self._debug_log.append("Touchscreen", f"{sent}/{total} sent, {acked} acked")

    def _on_thread_stopped(self) -> None:
        # Only safe to allow a new action (and thus a new
        # self._worker/self._thread reassignment) once the QThread has
        # actually stopped -- not merely once the worker reported it was
        # done, which races the still-shutting-down old thread.
        self._set_busy(False)

    def _on_finished(self, success: bool, message: str) -> None:
        self._debug_log.append("Touchscreen", f"-- {message}")
        if not success:
            text = message
            if "permission" in message.lower():
                text = f"{message}\n\n{SCREEN_PERMISSION_HINT}"
            QMessageBox.critical(self, "Screen Error", text)
