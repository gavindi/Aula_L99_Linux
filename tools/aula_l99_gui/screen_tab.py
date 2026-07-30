"""Touchscreen (aula_l99_screen) control tab: image upload + GIF upload."""
from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
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
from aula_l99_screen.device import find_screen

from .device_utils import SCREEN_PERMISSION_HINT, describe_screen, list_screen_devices
from .workers import ScreenUploadWorker, start_worker

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
SINGLE_IMAGE_TARGETS = {
    "photo-frame": screen_protocol.PHOTO_FRAME_FLASH_BASE,
    "background": screen_protocol.BACKGROUND_FLASH_BASE,
}
DEFAULT_GIF_DELAY = 50


def _pillow_missing_message() -> str:
    return "Pillow is required to load images (pip install pillow)."


class ScreenTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._devices: list = []
        self._thread = None
        self._worker = None
        self._busy = False
        self._action_buttons: list[QPushButton] = []

        self._image_path: str | None = None
        self._gif_folder_paths: list[str] = []
        self._gif_file_paths: list[str] = []
        self._gif_animated_path: str | None = None

        self._build_ui()
        self.refresh_devices()

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_device_group())
        layout.addWidget(self._build_single_image_group())
        layout.addWidget(self._build_gif_group())

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        layout.addWidget(self.log)

    def _build_device_group(self) -> QGroupBox:
        group = QGroupBox("Device")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.device_combo = QComboBox()
        row.addWidget(self.device_combo, stretch=1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_devices)
        row.addWidget(refresh_button)
        layout.addLayout(row)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return group

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
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedHeight(160)
        self.image_preview.setFrameShape(QLabel.Shape.Box)
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

        upload_button = QPushButton("Upload GIF")
        upload_button.clicked.connect(self._on_upload_gif)
        layout.addWidget(upload_button)
        self._action_buttons.append(upload_button)

        return group

    # -- device handling --------------------------------------------------

    def refresh_devices(self) -> None:
        self._devices = list_screen_devices()
        self.device_combo.clear()
        for device in self._devices:
            self.device_combo.addItem(describe_screen(device))

        try:
            found = find_screen()
        except FileNotFoundError:
            self.status_label.setText(
                "No AULA L99 touchscreen found. Plug it in and click Refresh."
            )
            self._set_actions_enabled(False)
            return

        index = next((i for i, d in enumerate(self._devices) if d.path == found.path), -1)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)

        self.status_label.setText(f"Using {found.path}")
        self._set_actions_enabled(True)

    def _current_device_path(self) -> str | None:
        index = self.device_combo.currentIndex()
        if 0 <= index < len(self._devices):
            return self._devices[index].path
        return None

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in self._action_buttons:
            button.setEnabled(enabled)

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
        device_path = self._current_device_path()
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

    def _refresh_gif_frame_list(self, labels: list[str]) -> None:
        self.gif_frame_list.clear()
        self.gif_frame_list.addItems(labels)

    def _collect_gif_frame_pixels(self) -> list[list[tuple[int, int, int]]] | None:
        if self.radio_folder.isChecked():
            paths = self._gif_folder_paths
        elif self.radio_files.isChecked():
            paths = self._gif_file_paths
        else:
            paths = None

        if paths is not None:
            if not paths:
                QMessageBox.warning(self, "Screen", "No frames selected.")
                return None
            frames = []
            for path in paths:
                try:
                    frames.append(self._pixels_from_image(self._load_image(path)))
                except OSError as exc:
                    QMessageBox.critical(self, "Screen", f"Could not open {path}:\n{exc}")
                    return None
            return frames

        if self._gif_animated_path is None:
            QMessageBox.warning(self, "Screen", "No animated GIF selected.")
            return None
        frames = []
        size = (screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT)
        with Image.open(self._gif_animated_path) as im:
            for frame in ImageSequence.Iterator(im):
                rgb = frame.convert("RGB")
                if rgb.size != size:
                    rgb = rgb.resize(size, Image.LANCZOS)
                frames.append(self._pixels_from_image(rgb))
        if not frames:
            QMessageBox.warning(self, "Screen", "That GIF has no frames.")
            return None
        return frames

    def _on_upload_gif(self) -> None:
        if self._busy:
            return
        if Image is None:
            QMessageBox.critical(self, "Screen", _pillow_missing_message())
            return
        device_path = self._current_device_path()
        if device_path is None:
            QMessageBox.warning(self, "Screen", "No device selected.")
            return

        frames = self._collect_gif_frame_pixels()
        if frames is None:
            return

        bad: dict[tuple[int, int, int], int] = {}
        for pixels in frames:
            for color in pixels:
                if not screen_protocol.is_safe_gif_color(*color):
                    bad[color] = bad.get(color, 0) + 1
        if bad:
            worst = sorted(bad.items(), key=lambda kv: -kv[1])[:10]
            lines = "\n".join(f"  rgb{color}: {count} px" for color, count in worst)
            QMessageBox.warning(
                self, "Screen",
                "These colors need dithering, which isn't supported -- every pixel "
                "must have R, G, or B at exactly 0 or 255:\n\n" + lines,
            )
            return

        try:
            blob = screen_protocol.build_gif_blob(
                frames, screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT,
                delay=self.gif_delay_spin.value(),
            )
        except ValueError as exc:
            QMessageBox.critical(self, "Screen", str(exc))
            return

        packets = screen_protocol.build_upload(blob, screen_protocol.GIF_FLASH_BASE)
        self.log.appendPlainText(f"{len(frames)} frame(s), {len(blob)} bytes")
        self._start_upload(device_path, packets)

    # -- shared upload plumbing ------------------------------------------

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _start_upload(self, device_path: str, packets: list[bytes]) -> None:
        self._busy = True
        self._set_actions_enabled(False)
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
        self._busy = False
        self._set_actions_enabled(True)

    def _on_finished(self, success: bool, message: str) -> None:
        self.log.appendPlainText(f"-- {message}")
        if not success:
            text = message
            if "permission" in message.lower():
                text = f"{message}\n\n{SCREEN_PERMISSION_HINT}"
            QMessageBox.critical(self, "Screen Error", text)
