"""Touchscreen (aula_l99_screen) control tab: image upload + GIF upload."""
from __future__ import annotations

import csv
import dataclasses
import io
import pathlib
import shutil
import subprocess
from collections import Counter

from PySide6.QtCore import QPointF, QRectF, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
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
    QSizePolicy,
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
# The preview is sized by the layout, tracking the panel's aspect (see
# PreviewLabel), but never grows past the panel's own 320x480: at 1:1 there
# is nothing further to show, and a tall window would otherwise keep handing
# it height it has no use for. The group pads underneath, so the column still
# runs down to the progress bar without the image stretching to match.
PREVIEW_MIN_HEIGHT = 440
PREVIEW_MAX_WIDTH = screen_protocol.PANEL_WIDTH
PREVIEW_MAX_HEIGHT = screen_protocol.PANEL_HEIGHT
# Loaded at 2x the panel's own 320x480 so the preview stays sharp when the
# window is tall; PreviewLabel scales this down to whatever height it gets.
PREVIEW_SOURCE_SIZE = QSize(640, 960)
SOURCE_IMAGE_FILTER = "Supported files (*.png *.jpg *.jpeg *.gif *.mp4)"
SINGLE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
MULTI_FRAME_SUFFIXES = {".gif", ".mp4"}

# Clip regions are held as fractions of the source rather than pixels, so the
# same numbers describe a still, a GIF and an .mp4 without anything having to
# know their pixel dimensions first -- ffmpeg's crop filter takes iw/ih
# expressions, and Pillow's crop() is one multiply away. It also means a clip
# survives the source being re-exported at a different resolution.
CLIP_FULL = (0.0, 0.0, 1.0, 1.0)
# How close the pointer has to get to an edge to grab it rather than the box,
# and the smallest the box may be dragged -- both in preview pixels, so the
# handles stay usable whatever the window size.
CLIP_HANDLE_PX = 9
CLIP_MIN_PX = 24


def _pillow_missing_message() -> str:
    return "Pillow is required to load images (pip install pillow)."


def _sane_clip(clip: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """`clip` forced back inside the source, for values off disk or a drag."""
    x, y, w, h = (float(v) for v in clip)
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    # A zero-width clip would crop to nothing and a too-wide one would run off
    # the edge; both are clamped rather than rejected, since the only caller
    # that can produce them is a hand-edited or truncated csv.
    w = min(max(w, 1e-3), 1.0 - x)
    h = min(max(h, 1e-3), 1.0 - y)
    return (x, y, w, h)


@dataclasses.dataclass
class SourceImage:
    """One entry in the build list: a file plus the region of it to use.

    The clip is the whole source by default, which is what every save written
    before clipping existed reloads as -- so an untouched build behaves
    exactly as it did when the sources were a bare list of paths.
    """

    path: str
    clip_x: float = 0.0
    clip_y: float = 0.0
    clip_w: float = 1.0
    clip_h: float = 1.0

    @property
    def clip(self) -> tuple[float, float, float, float]:
        return (self.clip_x, self.clip_y, self.clip_w, self.clip_h)

    @clip.setter
    def clip(self, value: tuple[float, float, float, float]) -> None:
        self.clip_x, self.clip_y, self.clip_w, self.clip_h = _sane_clip(value)


def _crop_box(
    clip: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int] | None:
    """`clip` as a pixel box for Pillow's crop(), or None for a whole source.

    Returning None for the full-frame case lets every caller skip the crop
    entirely, which is both faster and keeps the untouched path bit-for-bit
    what it was before clipping existed.
    """
    x, y, w, h = clip
    if (x, y, w, h) == CLIP_FULL:
        return None
    left = min(max(int(x * width), 0), max(width - 1, 0))
    top = min(max(int(y * height), 0), max(height - 1, 0))
    # At least one pixel each way: rounding a very small clip on a small
    # source can otherwise collapse the box, and Pillow returns a 0-wide
    # image that then fails to resize.
    right = min(max(round((x + w) * width), left + 1), width)
    bottom = min(max(round((y + h) * height), top + 1), height)
    return (left, top, right, bottom)


def _crop_to_panel(image, clip: tuple[float, float, float, float]):
    """`image` cropped to `clip`, then stretched to the panel's 320x480."""
    box = _crop_box(clip, image.width, image.height)
    if box is not None:
        image = image.crop(box)
    size = (screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT)
    if image.size != size:
        image = image.resize(size, Image.LANCZOS)
    return image


class PreviewLabel(QLabel):
    """The source preview, sized by its layout rather than by its contents.

    Holds the unscaled pixmap and rescales from it on every resize, so
    repeatedly growing and shrinking the window doesn't compound scaling
    losses.

    The height comes from the layout -- the preview spans from the source
    strip down to the progress bar -- and the width is then derived from it
    at the panel's own 320x480, so the frame is the shape of the screen being
    previewed. Qt can do height-for-width but not the reverse, hence setting
    the width from resizeEvent(); it settles in one extra layout pass, since
    this widget's width doesn't feed back into its own height.

    The source is drawn *fitted* inside that frame, at its own aspect, with
    the clip box on top of it. It used to be stretched to fill the frame,
    which was the honest thing to show back when the upload stretched the
    whole source to the panel -- but with a clip box the framing is now the
    box's job, and a box can only be positioned against a picture whose real
    shape and full extent are both visible.

    The vertical size policy is Ignored on purpose: the label must take the
    space the layout gives it and never ask for more. With a policy that
    honoured the pixmap's size hint, setting a freshly scaled pixmap from
    inside resizeEvent() would feed a new size hint back into the layout and
    can oscillate.
    """

    # x, y, w, h as fractions of the source. Emitted continuously while
    # dragging; `clip_committed` fires once on release, for the work that is
    # too expensive to redo per mouse-move (re-reading the file to restyle the
    # source strip's thumbnail).
    clip_changed = Signal(float, float, float, float)
    clip_committed = Signal()

    _CURSORS = {
        "move": Qt.CursorShape.SizeAllCursor,
        "t": Qt.CursorShape.SizeVerCursor,
        "b": Qt.CursorShape.SizeVerCursor,
        "l": Qt.CursorShape.SizeHorCursor,
        "r": Qt.CursorShape.SizeHorCursor,
        "tl": Qt.CursorShape.SizeFDiagCursor,
        "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor,
        "bl": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, placeholder: str) -> None:
        super().__init__(placeholder)
        self._placeholder = placeholder
        self._source: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._clip = CLIP_FULL
        self._drag_mode: str | None = None
        self._drag_from = QPointF()
        self._drag_clip = CLIP_FULL
        self.setObjectName("ImagePreview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        # Honoured regardless of the Ignored policy below -- that governs the
        # size *hint*, not the min/max bounds a layout has to respect.
        self.setMaximumHeight(PREVIEW_MAX_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)
        self.setFixedWidth(self._width_for_height(PREVIEW_MIN_HEIGHT))
        # So the edge/corner cursors appear on hover, not only once a button
        # is already down.
        self.setMouseTracking(True)

    @staticmethod
    def _width_for_height(height: int) -> int:
        """The width that makes this label the panel's own aspect."""
        width = round(height * screen_protocol.PANEL_WIDTH / screen_protocol.PANEL_HEIGHT)
        return max(1, min(width, PREVIEW_MAX_WIDTH))

    def set_source(
        self, pixmap: QPixmap | None, clip: tuple[float, float, float, float] = CLIP_FULL
    ) -> None:
        """Show `pixmap` clipped by `clip`, or the placeholder text for None."""
        self._source = pixmap if pixmap is not None and not pixmap.isNull() else None
        self._clip = _sane_clip(clip) if self._source is not None else CLIP_FULL
        self._drag_mode = None
        self.setText("" if self._source is not None else self._placeholder)
        self._rescale()

    def set_clip(self, clip: tuple[float, float, float, float]) -> None:
        """Move the box without reloading the source. Emits nothing -- the
        caller already knows the new value, since it supplied it."""
        self._clip = _sane_clip(clip)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        wanted = self._width_for_height(self.height())
        if wanted != self.width():
            # Re-runs the layout, which calls back in here with the new width
            # and the same height, where `wanted` matches and this stops.
            self.setFixedWidth(wanted)
        self._rescale()

    def _rescale(self) -> None:
        """Re-fit the source to the current widget size, always from the
        original, so repeated resizes don't compound scaling losses."""
        if self._source is None:
            self._scaled = None
        else:
            self._scaled = self._source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.update()

    # -- geometry ---------------------------------------------------------

    def _image_rect(self) -> QRectF:
        """Where the fitted source sits within the widget."""
        if self._scaled is None:
            return QRectF()
        size = self._scaled.size()
        return QRectF(
            (self.width() - size.width()) / 2.0,
            (self.height() - size.height()) / 2.0,
            size.width(),
            size.height(),
        )

    def _clip_rect(self) -> QRectF:
        image = self._image_rect()
        x, y, w, h = self._clip
        return QRectF(
            image.x() + x * image.width(),
            image.y() + y * image.height(),
            w * image.width(),
            h * image.height(),
        )

    def _handle_at(self, pos: QPointF) -> str | None:
        """Which part of the box `pos` would grab, or None for outside it."""
        if self._scaled is None:
            return None
        clip = self._clip_rect()
        grab = CLIP_HANDLE_PX
        if not (clip.left() - grab <= pos.x() <= clip.right() + grab
                and clip.top() - grab <= pos.y() <= clip.bottom() + grab):
            return None
        vertical = ("t" if abs(pos.y() - clip.top()) <= grab
                    else "b" if abs(pos.y() - clip.bottom()) <= grab else "")
        horizontal = ("l" if abs(pos.x() - clip.left()) <= grab
                      else "r" if abs(pos.x() - clip.right()) <= grab else "")
        mode = vertical + horizontal
        if mode:
            return mode
        return "move" if clip.contains(pos) else None

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:
        # Draws the styled background and border, plus the placeholder text
        # when there is no source. Everything below goes on top of it.
        super().paintEvent(event)
        if self._scaled is None:
            return

        painter = QPainter(self)
        image = self._image_rect()
        painter.drawPixmap(image.topLeft(), self._scaled)

        clip = self._clip_rect()
        # Dim what falls outside the box: the excluded part still has to be
        # visible to aim the box with, but should read as excluded.
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        inside = QPainterPath()
        inside.addRect(clip)
        painter.fillPath(shade.subtracted(inside), QColor(0, 0, 0, 130))

        # Two-tone border so it stays legible over both a light and a dark
        # picture, without either colour being trusted to have contrast.
        painter.setPen(QPen(QColor(0, 0, 0, 160), 3))
        painter.drawRect(clip)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
        painter.drawRect(clip)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 230))
        for point in self._handle_points(clip):
            painter.drawRect(QRectF(point.x() - 3.0, point.y() - 3.0, 6.0, 6.0))

    @staticmethod
    def _handle_points(clip: QRectF) -> list[QPointF]:
        mid_x, mid_y = clip.center().x(), clip.center().y()
        return [
            QPointF(clip.left(), clip.top()), QPointF(mid_x, clip.top()),
            QPointF(clip.right(), clip.top()), QPointF(clip.left(), mid_y),
            QPointF(clip.right(), mid_y), QPointF(clip.left(), clip.bottom()),
            QPointF(mid_x, clip.bottom()), QPointF(clip.right(), clip.bottom()),
        ]

    # -- dragging ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._scaled is None:
            super().mousePressEvent(event)
            return
        mode = self._handle_at(event.position())
        if mode is None:
            super().mousePressEvent(event)
            return
        self._drag_mode = mode
        self._drag_from = event.position()
        self._drag_clip = self._clip

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is None:
            # Hover: show which grab the pointer is currently over.
            mode = self._handle_at(event.position()) if self._scaled is not None else None
            self.setCursor(self._CURSORS.get(mode, Qt.CursorShape.ArrowCursor))
            super().mouseMoveEvent(event)
            return
        image = self._image_rect()
        if image.width() <= 0 or image.height() <= 0:
            return
        # Work in fractions of the source throughout, so the same arithmetic
        # holds however the preview happens to be scaled right now.
        dx = (event.position().x() - self._drag_from.x()) / image.width()
        dy = (event.position().y() - self._drag_from.y()) / image.height()
        self._apply_drag(dx, dy, CLIP_MIN_PX / image.width(), CLIP_MIN_PX / image.height())

    def _apply_drag(self, dx: float, dy: float, min_w: float, min_h: float) -> None:
        x, y, w, h = self._drag_clip
        if self._drag_mode == "move":
            # Slides without resizing, so it stops at the source's edge
            # rather than being clipped short against it.
            clip = (min(max(x + dx, 0.0), 1.0 - w), min(max(y + dy, 0.0), 1.0 - h), w, h)
        else:
            left, top, right, bottom = x, y, x + w, y + h
            # Each edge is free of the others -- the box takes whatever
            # width and height it is dragged to, and a crop that isn't the
            # panel's 2:3 is stretched to fit on upload, exactly as an
            # unclipped source of the wrong shape already was.
            if "l" in self._drag_mode:
                left = min(max(left + dx, 0.0), right - min_w)
            if "r" in self._drag_mode:
                right = max(min(right + dx, 1.0), left + min_w)
            if "t" in self._drag_mode:
                top = min(max(top + dy, 0.0), bottom - min_h)
            if "b" in self._drag_mode:
                bottom = max(min(bottom + dy, 1.0), top + min_h)
            clip = (left, top, right - left, bottom - top)
        self._clip = _sane_clip(clip)
        self.update()
        self.clip_changed.emit(*self._clip)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_mode is None:
            super().mouseReleaseEvent(event)
            return
        self._drag_mode = None
        self.clip_committed.emit()

    def leaveEvent(self, event) -> None:
        self.unsetCursor()
        super().leaveEvent(event)


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


PALETTE_SAMPLE_FRAMES = 8


def _save_frames_as_gif(frames: list[bytes], delay: int, path: pathlib.Path) -> None:
    """Write the local backup copy of what was just built.

    Every frame is mapped to one shared palette, derived from a handful of
    frames sampled across the animation. Letting Pillow's GIF encoder pick a
    palette per frame instead cost 78ms/frame against 5ms here, for the same
    file size -- and on a 200-frame animation that was ~15s of the build,
    spent on a file that is only ever used for the Saved Animations thumbnail
    and as a record of what was sent.
    """
    width, height = screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT
    # frombytes() takes the frame's buffer directly; the Image.new() +
    # putdata() pair it replaces walked the frame a pixel at a time.
    images = [Image.frombytes("RGB", (width, height), pixels) for pixels in frames]

    # Sample across the whole animation rather than trusting frame 0 to be
    # representative of it -- a scene change would otherwise leave every
    # later frame mapped to the opening shot's colours.
    step = max(1, len(images) // PALETTE_SAMPLE_FRAMES)
    sample = images[::step][:PALETTE_SAMPLE_FRAMES]
    strip = Image.new("RGB", (width, height * len(sample)))
    for i, image in enumerate(sample):
        strip.paste(image, (0, height * i))
    palette = strip.quantize(colors=256)

    mapped = [image.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
              for image in images]
    mapped[0].save(
        path,
        save_all=True,
        append_images=mapped[1:],
        duration=delay * 10,
        loop=0,
        optimize=False,
    )


def _evenly_spaced_indices(total: int, limit: int) -> list[int]:
    """Up to `limit` indices spread evenly over range(total).

    Sampling across the whole source rather than truncating to the first
    `limit` frames: a long animation's opening second is rarely
    representative of it, and the panel plays whatever it is given at one
    uniform delay anyway.
    """
    if limit <= 0 or total <= 0:
        return []
    if total <= limit:
        return list(range(total))
    return [i * total // limit for i in range(limit)]


def _per_source_frame_budget(source_paths: list[str]) -> int:
    """How many frames each multi-frame source may contribute.

    Split evenly rather than first-come-first-served, so a second GIF isn't
    silently reduced to nothing by whatever was listed ahead of it.
    """
    multi = [p for p in source_paths
             if pathlib.Path(p).suffix.lower() in MULTI_FRAME_SUFFIXES]
    return max(1, screen_protocol.MAX_GIF_FRAMES // max(len(multi), 1))


def _save_animation_config(
    csv_path: pathlib.Path, output_name: str, sources: list[SourceImage], delay: int | None
) -> None:
    # Source paths are written out in full (not just basename) so the
    # thumbnail strip can reopen the original files later -- their directory
    # isn't otherwise recoverable, unlike the output file which always sits
    # alongside this csv. delay is None for a single-image save, where the
    # column is meaningless -- written blank rather than a placeholder value.
    # The four clip columns were appended after the fact; _source_from_csv_row
    # treats a row without them as an unclipped source, so saves written
    # before clipping existed still load.
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow([output_name])
        for source in sources:
            writer.writerow(
                [source.path, "" if delay is None else delay]
                + [f"{value:.6g}" for value in source.clip]
            )


def _source_from_csv_row(row: list[str]) -> SourceImage:
    """One build-list entry from a saved config row.

    A row missing or mangling the clip columns falls back to the whole
    source: a save that can't describe its framing is still perfectly usable
    as a source list, and refusing to load it would lose the paths too.
    """
    try:
        clip = _sane_clip(tuple(float(value) for value in row[2:6]))
    except (ValueError, TypeError):
        clip = CLIP_FULL
    return SourceImage(row[0], *clip)


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
        # Frames the sources actually contain, before sampling down to the
        # panel's budget -- set on the conversion thread, read by
        # _on_convert_thread_stopped on the GUI thread once it has finished,
        # same handover as _local_save_path/_local_save_error above.
        self._source_frame_total = 0
        self._pending_upload_device_path: str | None = None
        self._busy = False
        self._device_ready = False
        self._action_buttons: list[QPushButton] = []

        self._build_sources: list[SourceImage] = []
        # Row of `_build_sources` the preview is currently showing, so a clip
        # drag knows which source it is editing. None when nothing is
        # selected, which is also what disables the crop controls.
        self._preview_index: int | None = None
        self._preview_size: QSize | None = None

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.addWidget(self._build_thumbnail_column())

        right = QVBoxLayout()
        right.addWidget(self._build_source_strip())

        # Preview on the left of this row, controls stacked to its right. The
        # row takes all the stretch in the column, which is what makes the
        # preview run the full height from the source strip down to the
        # progress bar.
        middle = QHBoxLayout()
        middle.addWidget(self._build_preview_group())

        controls = QVBoxLayout()
        controls.addWidget(self._build_send_to_device_group())
        controls.addWidget(self._build_gif_group())
        # Keeps both groups at their natural height, pinned to the top of the
        # column, instead of stretching to fill the preview's height.
        controls.addStretch(1)
        middle.addLayout(controls, 1)

        right.addLayout(middle, 1)

        self.progress_bar = QProgressBar()
        right.addWidget(self.progress_bar)

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

        return group

    def _build_preview_group(self) -> QGroupBox:
        # Its own group rather than living inside "Source Images", so it can
        # sit beside the control groups and span their full height.
        group = QGroupBox("Preview")
        layout = QVBoxLayout(group)
        self.source_preview = PreviewLabel("(no image selected)")
        self.source_preview.setToolTip(
            "Drag inside the box to move the crop, or its edges and corners "
            "to resize. Only what's inside the box is sent, stretched to the "
            "panel's 320x480."
        )
        self.source_preview.clip_changed.connect(self._on_clip_changed)
        self.source_preview.clip_committed.connect(self._on_clip_committed)
        layout.addWidget(self.source_preview)

        # Kept narrow enough not to widen the column past the preview itself,
        # which is what fixes this group's width -- hence the short readout
        # with the full detail in its tooltip.
        crop_row = QHBoxLayout()
        self.clip_label = QLabel("")
        crop_row.addWidget(self.clip_label)
        crop_row.addStretch(1)
        self.reset_clip_button = QPushButton("Reset Crop")
        self.reset_clip_button.clicked.connect(self._on_reset_clip)
        crop_row.addWidget(self.reset_clip_button)
        layout.addLayout(crop_row)

        # Padding, not stretch: the group still spans down to the progress
        # bar, but once the preview hits the panel's own size the leftover
        # height goes here instead of into the image.
        layout.addStretch(1)
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
            self._build_sources = []
            self._refresh_source_strip()
            return
        csv_path = current.data(Qt.ItemDataRole.UserRole)
        try:
            with csv_path.open(newline="") as fh:
                rows = list(csv.reader(fh))
        except OSError:
            return
        self._build_sources = [_source_from_csv_row(row) for row in rows[1:] if row]
        self._refresh_source_strip()

    def _refresh_source_strip(self) -> None:
        self.source_strip.clear()
        if Image is None:
            return
        for source in self._build_sources:
            item = QListWidgetItem(QIcon(self._load_source_thumbnail(source)), "")
            item.setToolTip(source.path)
            item.setData(Qt.ItemDataRole.UserRole, source.path)
            self.source_strip.addItem(item)
        self._sync_send_buttons()

    def _load_source_frame(self, path: str) -> QPixmap | None:
        """First frame of `path` at its own size, or None if unreadable.

        Kept separate from thumbnailing so the preview can ask for the frame
        unscaled and unclipped -- it draws the clip box over the whole source
        rather than showing the result of the crop.
        """
        try:
            with Image.open(path) as im:
                return self._to_pixmap(im.convert("RGB"))
        except Exception:  # noqa: BLE001 - not Pillow-openable, e.g. .mp4
            pass
        if pathlib.Path(path).suffix.lower() == ".mp4":
            frame = self._video_thumbnail_frame(path)
            if frame is not None:
                return self._to_pixmap(frame)
        return None

    def _load_source_thumbnail(
        self, source: SourceImage, size: QSize = STRIP_ICON_SIZE
    ) -> QPixmap:
        # Clipped, unlike the preview: the strip shows what each source
        # contributes to the upload, so a tile whose crop has been narrowed
        # should look narrowed.
        pixmap = self._load_source_frame(source.path)
        if pixmap is None:
            pixmap = QPixmap(size)
            pixmap.fill(Qt.GlobalColor.darkGray)
            return pixmap
        box = _crop_box(source.clip, pixmap.width(), pixmap.height())
        if box is not None:
            left, top, right, bottom = box
            pixmap = pixmap.copy(left, top, right - left, bottom - top)
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
        index = self.source_strip.row(current) if current is not None else -1
        if not 0 <= index < len(self._build_sources):
            self._preview_index = None
            self._preview_size = None
            self.source_preview.set_source(None)
            self._sync_clip_controls()
            return
        source = self._build_sources[index]
        self._preview_index = index
        frame = self._load_source_frame(source.path)
        # The source's own pixel size, before it is scaled down for display --
        # what the crop readout is quoted in, since that is the resolution the
        # crop is actually taken at.
        self._preview_size = frame.size() if frame is not None else None
        if frame is not None:
            frame = frame.scaled(
                PREVIEW_SOURCE_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.source_preview.set_source(frame, source.clip)
        self._sync_clip_controls()

    def _sync_clip_controls(self) -> None:
        source = self._current_source()
        if source is None:
            self.clip_label.setText("")
            self.clip_label.setToolTip("")
            self.reset_clip_button.setEnabled(False)
            return
        self.reset_clip_button.setEnabled(source.clip != CLIP_FULL)
        x, y, w, h = source.clip
        if self._preview_size is None:
            # An .mp4 whose thumbnail couldn't be decoded: there is no pixel
            # size to quote, so fall back to the fractions themselves.
            self.clip_label.setText(f"crop {w:.0%} x {h:.0%}")
            self.clip_label.setToolTip(f"at {x:.0%}, {y:.0%} of the source")
            return
        width, height = self._preview_size.width(), self._preview_size.height()
        box = _crop_box(source.clip, width, height) or (0, 0, width, height)
        left, top, right, bottom = box
        self.clip_label.setText(f"crop {right - left} x {bottom - top}")
        self.clip_label.setToolTip(
            f"{right - left} x {bottom - top} at ({left}, {top}) of "
            f"{width} x {height}, sent as "
            f"{screen_protocol.PANEL_WIDTH} x {screen_protocol.PANEL_HEIGHT}"
        )

    def _current_source(self) -> SourceImage | None:
        if self._preview_index is None or self._preview_index >= len(self._build_sources):
            return None
        return self._build_sources[self._preview_index]

    def _on_clip_changed(self, x: float, y: float, w: float, h: float) -> None:
        source = self._current_source()
        if source is None:
            return
        source.clip = (x, y, w, h)
        # Readout only -- the strip thumbnail waits for the drag to finish,
        # since restyling it means re-reading the source file.
        self._sync_clip_controls()

    def _on_clip_committed(self) -> None:
        source = self._current_source()
        item = self.source_strip.item(self._preview_index) if source is not None else None
        if item is None:
            return
        # Just this one tile, not _refresh_source_strip(): rebuilding the
        # whole strip clears it, which drops the selection and would take the
        # preview down with it on every drag.
        item.setIcon(QIcon(self._load_source_thumbnail(source)))

    def _on_reset_clip(self) -> None:
        source = self._current_source()
        if source is None:
            return
        source.clip = CLIP_FULL
        self.source_preview.set_clip(CLIP_FULL)
        self._on_clip_committed()
        self._sync_clip_controls()

    def _on_choose_source_images(self) -> None:
        if Image is None:
            QMessageBox.critical(self, "Screen", _pillow_missing_message())
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose Source Images", filter=SOURCE_IMAGE_FILTER
        )
        if not paths:
            return
        self._build_sources.extend(SourceImage(path) for path in paths)
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
        del self._build_sources[index]
        self._refresh_source_strip()

    def _build_send_to_device_group(self) -> QGroupBox:
        group = QGroupBox("Send to Device")
        # Stacked, not in a row: the group sits in a narrow column beside the
        # preview now, where three buttons side by side would either be
        # clipped or force the column wider than the controls need.
        layout = QVBoxLayout(group)

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

        gap_row = QHBoxLayout()
        gap_row.addWidget(QLabel("Packet gap (ms):"))
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
        gap_row.addWidget(self.packet_gap_spin)
        gap_row.addStretch(1)
        layout.addLayout(gap_row)

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
        # These need extra conditions (content of `_build_sources`) on
        # top of the usual device-ready/not-busy gating, so they're kept out
        # of `_action_buttons` and synced here instead -- called both when
        # busy/device-ready changes (_sync_actions) and whenever the source
        # list's contents change (_refresh_source_strip).
        base_enabled = self._device_ready and not self._busy
        single_image = (
            len(self._build_sources) == 1
            and pathlib.Path(self._build_sources[0].path).suffix.lower()
            in SINGLE_IMAGE_SUFFIXES
        )
        self.background_button.setEnabled(base_enabled and single_image)
        self.photo_frame_button.setEnabled(base_enabled and single_image)
        self.customized_animation_button.setEnabled(
            base_enabled and len(self._build_sources) >= 1
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
        self._sync_actions()
        self._sync_list_buttons()

    # -- image loading ------------------------------------------------------

    def _load_image(self, path: str, clip: tuple[float, float, float, float] = CLIP_FULL):
        image = Image.open(path)
        image = image.convert("RGB")
        return _crop_to_panel(image, clip)

    def _pixels_from_image(self, image) -> bytes:
        # Flat RGB888 -- the form screen_protocol works in natively. A
        # 320x480 frame is 460800 bytes this way and 12.3 MB as the list of
        # (r, g, b) tuples getdata()/get_flattened_data() produce; at the
        # 200-frame maximum that is 92 MB against 2.5 GB.
        return image.tobytes("raw", "RGB")

    def _to_pixmap(self, image) -> QPixmap:
        data = image.tobytes("raw", "RGB")
        qimage = QImage(
            data, image.width, image.height, image.width * 3,
            QImage.Format.Format_RGB888,
        )
        return QPixmap.fromImage(qimage.copy())

    # -- single image upload --------------------------------------------

    def _on_send_single_image(self, address: int) -> None:
        if self._busy or len(self._build_sources) != 1:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Screen", "No device selected.")
            return
        source = self._build_sources[0]
        path = source.path
        try:
            image = self._load_image(path, source.clip)
        except OSError as exc:
            QMessageBox.critical(self, "Screen", f"Could not open {path}:\n{exc}")
            return

        try:
            save_path = self._current_save_target().with_suffix(".png")
            image.save(save_path)
            _save_animation_config(
                save_path.with_suffix(".csv"), save_path.name, [source], None)
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

    def _current_gif_sources(self) -> list[SourceImage]:
        # Copies, not the live objects: this list is handed to the conversion
        # thread, which writes it out to the csv long after the GUI thread is
        # free to keep editing clips.
        return [dataclasses.replace(source) for source in self._build_sources]

    def _frames_from_gif(
        self, path: str, limit: int, clip: tuple[float, float, float, float] = CLIP_FULL
    ) -> list[bytes]:
        frames = []
        with Image.open(path) as im:
            total = getattr(im, "n_frames", 1)
            self._source_frame_total += total
            # Decide which frames to keep *before* decoding any of them.
            # Iterating still has to seek past the skipped ones (a GIF is a
            # sequential format), but the convert/resize/store work -- which
            # is all of the cost -- only happens for the ones being kept.
            keep = set(_evenly_spaced_indices(total, limit))
            for index, frame in enumerate(ImageSequence.Iterator(im)):
                if index not in keep:
                    continue
                # One clip for the whole source, applied to every frame it
                # contributes -- the box is a property of the file, not of a
                # position within it.
                frames.append(self._pixels_from_image(
                    _crop_to_panel(frame.convert("RGB"), clip)))
        if not frames:
            raise ValueError(f"{path} has no frames.")
        return frames

    def _collect_gif_frame_pixels(self, delay: int) -> list[bytes]:
        # Raises rather than showing a QMessageBox and returning None: this
        # runs off the GUI thread now (see _build_gif_packets), and Qt
        # widgets aren't thread-safe. _on_convert_thread_stopped turns the
        # exception message into a dialog back on the GUI thread once the
        # background job (a CallableResultWorker) finishes.
        if not self._build_sources:
            raise ValueError("No source images selected.")
        # Every multi-frame source is sampled down to its share of the
        # panel's frame budget as it is read. Without this a long source
        # runs to completion and then fails at the very end: the format's
        # frame-count field is one byte, so a 4883-frame GIF spent minutes
        # decoding and writing a local copy only to raise on encode.
        budget = _per_source_frame_budget([s.path for s in self._build_sources])
        self._source_frame_total = 0
        frames: list[bytes] = []
        for source in self._build_sources:
            path = source.path
            suffix = pathlib.Path(path).suffix.lower()
            if suffix == ".mp4":
                frames.extend(
                    self._extract_video_frames(path, delay, budget, source.clip))
            elif suffix == ".gif":
                frames.extend(self._frames_from_gif(path, budget, source.clip))
            else:
                try:
                    frames.append(
                        self._pixels_from_image(self._load_image(path, source.clip)))
                except OSError as exc:
                    raise ValueError(f"Could not open {path}: {exc}") from exc
        # Safety net for the mixed-source case, where per-source budgets can
        # still add up to more than the panel takes (e.g. many stills).
        if len(frames) > screen_protocol.MAX_GIF_FRAMES:
            keep = _evenly_spaced_indices(len(frames), screen_protocol.MAX_GIF_FRAMES)
            frames = [frames[i] for i in keep]
        return frames

    def _video_duration_seconds(self, path: str) -> float | None:
        """Runs ffprobe, or None if it isn't installed / can't say."""
        if shutil.which("ffprobe") is None:
            return None
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, check=True,
            )
            duration = float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError):
            return None
        return duration if duration > 0 else None

    def _extract_video_frames(self, path: str, delay: int, limit: int,
                              clip: tuple[float, float, float, float] = CLIP_FULL
                              ) -> list[bytes]:
        """Decodes video frames via a system ffmpeg subprocess -- no video
        decoding library is otherwise a dependency of this project, and
        shelling out avoids adding one (PyAV/opencv-python) just for this.

        Samples at fps = 100/delay so the extracted frame count matches the
        same "Delay (centiseconds)" spinbox every other source uses for
        playback timing, rather than pulling every frame of what's typically
        a 24-60fps source into what's a small, slow panel to redraw.

        `limit` caps the result at the panel's frame budget. When ffprobe can
        report the duration, the sampling rate is lowered to spread that many
        frames across the whole clip; otherwise `-frames:v` truncates it,
        which bounds the work either way but keeps only the opening.

        `clip` becomes a crop filter, expressed against ffmpeg's own iw/ih so
        the video's dimensions never have to be probed for it.
        """
        if shutil.which("ffmpeg") is None:
            raise ValueError(
                "ffmpeg is required to convert video and wasn't found on PATH. "
                "Install it (e.g. apt install ffmpeg) and try again."
            )

        width, height = screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT
        fps = 100.0 / delay
        duration = self._video_duration_seconds(path)
        if duration is not None and fps * duration > limit:
            fps = limit / duration
        # fps first, so the crop and scale only run on the frames that are
        # actually being kept.
        filters = [f"fps={fps}"]
        x, y, w, h = clip
        if clip != CLIP_FULL:
            filters.append(f"crop=iw*{w:.6f}:ih*{h:.6f}:iw*{x:.6f}:ih*{y:.6f}")
        # A plain scale, so the crop fills the panel. This used to letterbox
        # (force_original_aspect_ratio=decrease + pad), which was reasonable
        # when there was no way to choose the framing -- but it would now
        # quietly add bars around a region the user had deliberately picked,
        # and it is the one source type that wouldn't match the preview.
        # Stills and GIFs have always stretched.
        filters.append(f"scale={width}:{height}")
        command = [
            "ffmpeg", "-i", path,
            "-vf", ",".join(filters),
            "-frames:v", str(limit),
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
        # ffmpeg's rgb24 output is already exactly the flat RGB888 layout
        # screen_protocol wants, so each frame is a plain slice -- no
        # reshaping pass over the pixels at all.
        frames = [data[offset:offset + frame_size]
                  for offset in range(0, usable, frame_size)]
        if not frames:
            raise ValueError("That video produced no frames.")
        return frames

    def _ensure_safe_colors(self, frames: list[bytes]) -> None:
        # Distinct colours first (a C-level zip over three strided slices),
        # counting occurrences only for the ones that turn out to be unsafe
        # -- the per-pixel pass this replaces walked every pixel of every
        # frame in Python to build a report that is usually never shown.
        bad: dict[tuple[int, int, int], int] = {}
        for pixels in frames:
            for color in set(zip(pixels[0::3], pixels[1::3], pixels[2::3])):
                if not screen_protocol.is_safe_gif_color(*color):
                    bad[color] = 0
        if bad:
            for pixels in frames:
                for color, count in Counter(
                        zip(pixels[0::3], pixels[1::3], pixels[2::3])).items():
                    if color in bad:
                        bad[color] += count
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
                self._current_gif_sources(), delay,
            )
            self._local_save_path = save_path
            self._local_save_error = None
        except Exception as exc:  # must not abort the upload over a backup failure
            self._local_save_path = None
            self._local_save_error = str(exc)

        frame_count = len(frames)
        blob = screen_protocol.build_gif_blob(
            frames, screen_protocol.PANEL_WIDTH, screen_protocol.PANEL_HEIGHT,
            delay=delay, dither=dither,
        )
        # Nothing downstream reads the frames again, and this thread's locals
        # stay alive until it exits -- so without these the source pixels
        # would sit in memory alongside the blob, and then alongside the
        # packet list, for the whole packing phase and the upload after it.
        del frames
        blob_len = len(blob)
        packets = screen_protocol.build_upload(blob, screen_protocol.GIF_FLASH_BASE)
        del blob
        return packets, frame_count, blob_len

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
        if self._source_frame_total > frame_count:
            self._debug_log.append(
                "Touchscreen",
                f"sampled {frame_count} of {self._source_frame_total} source frame(s) "
                f"-- the panel's format carries at most "
                f"{screen_protocol.MAX_GIF_FRAMES}",
            )
        if blob_len > screen_protocol.VENDOR_MAX_GIF_BLOB_BYTES:
            # Warning only, deliberately: nothing establishes how much flash
            # is mapped above the GIF base, so this reports that the upload
            # has left the range the vendor app could ever have written
            # rather than second-guessing the panel. See
            # protocol.VENDOR_MAX_GIF_BLOB_BYTES for where the figure
            # comes from.
            self._debug_log.append(
                "Touchscreen",
                f"warning: {blob_len / 1e6:.1f} MB exceeds the "
                f"{screen_protocol.VENDOR_MAX_GIF_BLOB_BYTES / 1e6:.1f} MB the vendor "
                f"app could ever write -- dithered frames encode much larger than its "
                f"own do, and how much flash is mapped there is unverified",
            )
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
