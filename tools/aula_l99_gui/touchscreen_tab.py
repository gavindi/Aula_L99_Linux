"""Touchscreen (aula_l99_screen) control tab: image upload + GIF upload."""
from __future__ import annotations

import pathlib
import shutil
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
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

from .device_tab import DeviceSelector
from .device_utils import SCREEN_PERMISSION_HINT
from .workers import CallableResultWorker, ScreenUploadWorker, start_worker

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
SINGLE_IMAGE_TARGETS = {
    "photo-frame": screen_protocol.PHOTO_FRAME_FLASH_BASE,
    "background": screen_protocol.BACKGROUND_FLASH_BASE,
}
DEFAULT_GIF_DELAY = 50


def _pillow_missing_message() -> str:
    return "Pillow is required to load images (pip install pillow)."


class TouchscreenTab(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, selector: DeviceSelector) -> None:
        super().__init__()
        self._selector = selector
        self._thread = None
        self._worker = None
        self._convert_thread = None
        self._convert_worker = None
        self._convert_result: tuple[list[bytes], int, int] | None = None
        self._convert_error = ""
        self._pending_upload_device_path: str | None = None
        self._busy = False
        self._device_ready = False
        self._action_buttons: list[QPushButton] = []

        self._image_path: str | None = None
        self._gif_folder_paths: list[str] = []
        self._gif_file_paths: list[str] = []
        self._gif_animated_path: str | None = None
        self._gif_video_path: str | None = None

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_single_image_group())
        layout.addWidget(self._build_gif_group())

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        layout.addWidget(self.log)

    def _build_single_image_group(self) -> QGroupBox:
        group = QGroupBox("Upload Image")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Target:"))
        self.target_combo = QComboBox()
        for name, address in SINGLE_IMAGE_TARGETS.items():
            self.target_combo.addItem(name, address)
        row.addWidget(self.target_combo)

        choose_button = QPushButton("Choose Image…")
        choose_button.clicked.connect(self._on_choose_image)
        row.addWidget(choose_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.image_preview = QLabel("(no image selected)")
        # Styled as a panel by theme.py rather than a bare QFrame box, so the
        # background image doesn't show through behind the preview.
        self.image_preview.setObjectName("ImagePreview")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedHeight(160)
        layout.addWidget(self.image_preview)

        upload_button = QPushButton("Upload")
        upload_button.clicked.connect(self._on_upload_image)
        layout.addWidget(upload_button)
        self._action_buttons.append(upload_button)

        return group

    def _build_gif_group(self) -> QGroupBox:
        group = QGroupBox("Upload GIF")
        layout = QVBoxLayout(group)

        self._gif_source_group = QButtonGroup(self)

        folder_row = QHBoxLayout()
        self.radio_folder = QRadioButton("Folder of frames")
        self.radio_folder.setChecked(True)
        self._gif_source_group.addButton(self.radio_folder)
        folder_row.addWidget(self.radio_folder)
        folder_button = QPushButton("Choose Folder…")
        folder_button.clicked.connect(self._on_choose_gif_folder)
        folder_row.addWidget(folder_button)
        folder_row.addStretch(1)
        layout.addLayout(folder_row)

        files_row = QHBoxLayout()
        self.radio_files = QRadioButton("Multiple image files")
        self._gif_source_group.addButton(self.radio_files)
        files_row.addWidget(self.radio_files)
        files_button = QPushButton("Choose Files…")
        files_button.clicked.connect(self._on_choose_gif_files)
        files_row.addWidget(files_button)
        files_row.addStretch(1)
        layout.addLayout(files_row)

        gif_row = QHBoxLayout()
        self.radio_gif = QRadioButton("Animated GIF file")
        self._gif_source_group.addButton(self.radio_gif)
        gif_row.addWidget(self.radio_gif)
        gif_button = QPushButton("Choose GIF…")
        gif_button.clicked.connect(self._on_choose_gif_animated)
        gif_row.addWidget(gif_button)
        gif_row.addStretch(1)
        layout.addLayout(gif_row)

        video_row = QHBoxLayout()
        self.radio_video = QRadioButton("Video (MP4)")
        self._gif_source_group.addButton(self.radio_video)
        video_row.addWidget(self.radio_video)
        video_button = QPushButton("Choose Video…")
        video_button.clicked.connect(self._on_choose_gif_video)
        video_row.addWidget(video_button)
        video_row.addStretch(1)
        layout.addLayout(video_row)

        self.gif_frame_list = QListWidget()
        self.gif_frame_list.setMaximumHeight(100)
        layout.addWidget(self.gif_frame_list)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Delay (centiseconds):"))
        self.gif_delay_spin = QSpinBox()
        self.gif_delay_spin.setRange(1, 1000)
        self.gif_delay_spin.setValue(DEFAULT_GIF_DELAY)
        delay_row.addWidget(self.gif_delay_spin)
        delay_row.addStretch(1)
        layout.addLayout(delay_row)

        dither_row = QHBoxLayout()
        self.dither_checkbox = QCheckBox("Dither")
        self.dither_checkbox.setChecked(True)
        dither_row.addWidget(self.dither_checkbox)
        dither_row.addStretch(1)
        layout.addLayout(dither_row)

        upload_button = QPushButton("Upload GIF")
        upload_button.clicked.connect(self._on_upload_gif)
        layout.addWidget(upload_button)
        self._action_buttons.append(upload_button)

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

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
        self._sync_actions()

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

    def _on_choose_image(self) -> None:
        if Image is None:
            QMessageBox.critical(self, "Screen", _pillow_missing_message())
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose Image")
        if not path:
            return
        try:
            image = self._load_image(path)
        except OSError as exc:
            QMessageBox.critical(self, "Screen", f"Could not open {path}:\n{exc}")
            return
        self._image_path = path
        pixmap = self._to_pixmap(image)
        self.image_preview.setPixmap(
            pixmap.scaled(
                self.image_preview.width(), self.image_preview.height(),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_upload_image(self) -> None:
        if self._busy:
            return
        if self._image_path is None:
            QMessageBox.warning(self, "Screen", "No image selected.")
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Screen", "No device selected.")
            return

        image = self._load_image(self._image_path)
        blob = screen_protocol.build_image_file(
            image.tobytes(), screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT
        )
        address = self.target_combo.currentData()
        packets = screen_protocol.build_upload(blob, address)
        self._start_upload(device_path, packets)

    # -- GIF source selection ------------------------------------------

    def _on_choose_gif_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Folder of Frames")
        if not folder:
            return
        paths = sorted(
            str(p) for p in pathlib.Path(folder).iterdir()
            if p.suffix.lower() in IMAGE_EXTENSIONS
        )
        if not paths:
            QMessageBox.warning(self, "Screen", "No images found in that folder.")
            return
        self._gif_folder_paths = paths
        self.radio_folder.setChecked(True)
        self._refresh_gif_frame_list([pathlib.Path(p).name for p in paths])

    def _on_choose_gif_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose Frame Images")
        if not paths:
            return
        self._gif_file_paths = list(paths)
        self.radio_files.setChecked(True)
        self._refresh_gif_frame_list([pathlib.Path(p).name for p in paths])

    def _on_choose_gif_animated(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose Animated GIF", filter="GIF (*.gif)")
        if not path:
            return
        self._gif_animated_path = path
        self.radio_gif.setChecked(True)
        self._refresh_gif_frame_list([f"{pathlib.Path(path).name} (all frames)"])

    def _on_choose_gif_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose Video", filter="Video (*.mp4)")
        if not path:
            return
        self._gif_video_path = path
        self.radio_video.setChecked(True)
        self._refresh_gif_frame_list([f"{pathlib.Path(path).name} (sampled at the delay below)"])

    def _refresh_gif_frame_list(self, labels: list[str]) -> None:
        self.gif_frame_list.clear()
        self.gif_frame_list.addItems(labels)

    def _collect_gif_frame_pixels(self, delay: int) -> list[list[tuple[int, int, int]]]:
        # Raises rather than showing a QMessageBox and returning None: this
        # runs off the GUI thread now (see _build_gif_packets), and Qt
        # widgets aren't thread-safe. _on_convert_thread_stopped turns the
        # exception message into a dialog back on the GUI thread once the
        # background job (a CallableResultWorker) finishes.
        if self.radio_video.isChecked():
            if self._gif_video_path is None:
                raise ValueError("No video selected.")
            return self._extract_video_frames(self._gif_video_path, delay)

        if self.radio_folder.isChecked():
            paths = self._gif_folder_paths
        elif self.radio_files.isChecked():
            paths = self._gif_file_paths
        else:
            paths = None

        if paths is not None:
            if not paths:
                raise ValueError("No frames selected.")
            frames = []
            for path in paths:
                try:
                    frames.append(self._pixels_from_image(self._load_image(path)))
                except OSError as exc:
                    raise ValueError(f"Could not open {path}: {exc}") from exc
            return frames

        if self._gif_animated_path is None:
            raise ValueError("No animated GIF selected.")
        frames = []
        size = (screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT)
        with Image.open(self._gif_animated_path) as im:
            for frame in ImageSequence.Iterator(im):
                rgb = frame.convert("RGB")
                if rgb.size != size:
                    rgb = rgb.resize(size, Image.LANCZOS)
                frames.append(self._pixels_from_image(rgb))
        if not frames:
            raise ValueError("That GIF has no frames.")
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

    def _build_gif_packets(self, dither: bool, delay: int) -> tuple[list[bytes], int, int]:
        """Everything slow about a GIF upload: decode/resize every source
        frame, then protocol.py's dithering + CRC computation. Runs on a
        background thread (see _on_upload_gif) -- profiled at ~3s for just a
        10-frame dithered GIF, which is long enough to freeze the window if
        run inline with the button click, as it used to be.
        """
        frames = self._collect_gif_frame_pixels(delay)
        if not dither:
            self._ensure_safe_colors(frames)
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

        self._set_busy(True)
        self.log.clear()
        self.log.appendPlainText("Converting frames…")

        # Separate worker/thread attributes from the upload phase's
        # (self._worker/self._thread, set in _start_upload) -- both are
        # reassigned on their own schedule and would otherwise race each
        # other's "only safe once the old QThread has actually stopped" rule.
        self._pending_upload_device_path = device_path
        self._convert_worker = CallableResultWorker(
            lambda: self._build_gif_packets(dither, delay)
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
        self.log.appendPlainText(f"{frame_count} frame(s), {blob_len} bytes")
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
        self._worker = ScreenUploadWorker(device_path, packets)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._on_thread_stopped)

    def _on_progress(self, sent: int, total: int, acked: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(sent)
        self.log.appendPlainText(f"{sent}/{total} sent, {acked} acked")

    def _on_thread_stopped(self) -> None:
        # Only safe to allow a new action (and thus a new
        # self._worker/self._thread reassignment) once the QThread has
        # actually stopped -- not merely once the worker reported it was
        # done, which races the still-shutting-down old thread.
        self._set_busy(False)

    def _on_finished(self, success: bool, message: str) -> None:
        self.log.appendPlainText(f"-- {message}")
        if not success:
            text = message
            if "permission" in message.lower():
                text = f"{message}\n\n{SCREEN_PERMISSION_HINT}"
            QMessageBox.critical(self, "Screen Error", text)
