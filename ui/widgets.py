"""自定义控件：可点击进度条、圆角封面、可拖动排序的歌曲表。"""
from __future__ import annotations

from PySide6.QtCore import (
    QBuffer,
    QIODevice,
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QSlider,
    QStyle,
    QTableView,
    QToolButton,
    QWidget,
)

from .icons import make_icon, make_pixmap
from .theme import ACCENT, MUTED

ROWS_MIME = "application/x-lumen-rows"


class ClickSlider(QSlider):
    """点击轨道即可跳转的滑块（默认 QSlider 只能拖手柄）。"""

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(16)

    def _value_at(self, x: float) -> int:
        style = self.style()
        handle = style.pixelMetric(QStyle.PixelMetric.PM_SliderLength, None, self)
        span = max(1, self.width() - handle)
        pos = int(x - handle / 2)
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos, span, self.invertedAppearance()
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            self.setSliderDown(True)
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.isSliderDown():
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AlbumCover(QWidget):
    """圆角封面，没有内嵌封面时用渐变占位。"""

    def __init__(self, size: int = 58, radius: int = 10, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(size, size))
        self._radius = radius
        self._pixmap: QPixmap | None = None
        self._seed = 0

    def set_cover(self, data: bytes | None, seed: int = 0) -> None:
        self._seed = seed
        # 内嵌封面常常是 1000×1000 的大图，先按控件实际像素尺寸解码，
        # 别整张解码完再缩（一张 1500² 的图解码要几十毫秒）。
        self._pixmap = _cover_pixmap(
            data, self.width(), self.height(), self.devicePixelRatioF()
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        painter.setClipPath(path)

        if self._pixmap is not None:
            # 解码时已经裁成控件比例，这里直接铺满即可
            painter.drawPixmap(self.rect(), self._pixmap)
        else:
            hue = 206 + (self._seed * 17) % 62
            start = QColor.fromHsv(hue, 76, 242)
            end = QColor.fromHsv((hue + 24) % 360, 135, 202)
            gradient = QLinearGradient(0, 0, rect.width(), rect.height())
            gradient.setColorAt(0.0, start)
            gradient.setColorAt(1.0, end)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRect(rect)
            icon_side = max(14, int(rect.width() * 0.36))
            note = make_pixmap("music", "#FFFFFF", icon_side)
            painter.setOpacity(0.92)
            painter.drawPixmap(
                QPointF(rect.center().x() - icon_side / 2, rect.center().y() - icon_side / 2),
                note,
            )

        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(20, 23, 31, 22), 1))
        painter.drawPath(path)


def _cover_pixmap(data: bytes | None, width: int, height: int,
                  ratio: float = 1.0) -> QPixmap | None:
    """把内嵌封面解码成「正好铺满 width×height」的位图。"""
    if not data or width <= 0 or height <= 0:
        return None
    buffer = QBuffer()
    buffer.setData(data)
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        return None

    reader = QImageReader(buffer)
    reader.setAutoTransform(True)          # 手机拍的图会带 EXIF 方向
    target_w = max(1, int(round(width * ratio)))
    target_h = max(1, int(round(height * ratio)))

    source = reader.size()
    if source.isValid() and source.width() > 0 and source.height() > 0:
        # 只缩小不放大：解码时就按需要的最小尺寸解
        scale = min(source.width() / target_w, source.height() / target_h)
        if scale > 1.2:
            reader.setScaledSize(
                QSize(max(1, int(source.width() / scale)),
                      max(1, int(source.height() / scale)))
            )

    image = reader.read()
    if image.isNull():
        return None

    scaled = image.scaled(
        target_w, target_h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - target_w) // 2)
    y = max(0, (scaled.height() - target_h) // 2)
    scaled = scaled.copy(x, y, min(target_w, scaled.width()), min(target_h, scaled.height()))

    pixmap = QPixmap.fromImage(scaled)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon_button(name: str, color: str = MUTED, size: int = 18,
                button_size: int = 32, tooltip: str = "",
                checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setObjectName("IconButton")
    button.setIcon(make_icon(name, color, size))
    button.setIconSize(QSize(size, size))
    button.setFixedSize(button_size, button_size)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setCheckable(checkable)
    if tooltip:
        button.setToolTip(tooltip)
    return button


class HLine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {ACCENT}14;")


class SongTable(QTableView):
    """歌曲表格：支持用鼠标拖动行来调整播放顺序。

    拖动逻辑自己实现（不接管 Qt 的 DnD 模型机制），因此：
    · 拖动行时只调整顺序，不影响文件本身；
    · 外部拖入的文件夹 / 音频文件仍然交给主窗口处理。
    """

    rowsDropped = Signal(list, int)   # (选中行号升序, 插入点行号)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setDropIndicatorShown(False)
        self.setDragDropOverwriteMode(False)
        self._press_pos: QPoint | None = None
        self._press_row = -1
        self._drop_row = -1

    # ---------------------------------------------------------------- 拖动
    def selected_rows(self) -> list[int]:
        model = self.selectionModel()
        if model is None:
            return []
        return sorted({index.row() for index in model.selectedRows()})

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            index = self.indexAt(self._press_pos)
            self._press_row = index.row() if index.isValid() else -1
        else:
            self._press_pos = None
            self._press_row = -1
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._press_pos is not None
            and self._press_row >= 0
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            moved = event.position().toPoint() - self._press_pos
            if moved.manhattanLength() >= QApplication.startDragDistance():
                self._begin_drag()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        self._press_row = -1
        super().mouseReleaseEvent(event)

    def _begin_drag(self) -> None:
        rows = self.selected_rows()
        if self._press_row not in rows:
            rows = [self._press_row]
        rows = [row for row in rows if row >= 0]
        if not rows:
            return

        mime = QMimeData()
        mime.setData(ROWS_MIME, ",".join(str(row) for row in rows).encode())
        mime.setText("lumen-rows")

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(len(rows)))
        drag.setHotSpot(QPoint(14, 14))
        self._press_pos = None
        self._press_row = -1
        drag.exec(Qt.DropAction.MoveAction)

    @staticmethod
    def _drag_pixmap(count: int) -> QPixmap:
        text = f"移动 {count} 首歌曲" if count > 1 else "移动这首歌曲"
        pixmap = QPixmap(150, 30)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, 150, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(35, 38, 47, 232))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#FFFFFF"))
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return pixmap

    # ---------------------------------------------------------------- 放置
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(ROWS_MIME):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()   # 外部文件拖入 → 冒泡给主窗口

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(ROWS_MIME):
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        pos = event.position().toPoint()
        self._auto_scroll(pos)
        row = self._insert_row_at(pos)
        if row != self._drop_row:
            self._drop_row = row
            self.viewport().update()

    def _auto_scroll(self, pos: QPoint) -> None:
        """拖到表格上下边缘时自动滚动，方便长列表里挪动歌曲。"""
        bar = self.verticalScrollBar()
        margin = 30
        height = self.viewport().height()
        if pos.y() < margin:
            bar.setValue(bar.value() - max(8, (margin - pos.y()) // 2))
        elif pos.y() > height - margin:
            bar.setValue(bar.value() + max(8, (pos.y() - height + margin) // 2))

    def dragLeaveEvent(self, event):
        self._clear_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        data = event.mimeData()
        if not data.hasFormat(ROWS_MIME):
            event.ignore()
            return
        rows: list[int] = []
        try:
            payload = bytes(data.data(ROWS_MIME)).decode()
            rows = [int(part) for part in payload.split(",") if part.strip()]
        except (TypeError, ValueError, UnicodeDecodeError):
            rows = self.selected_rows()
        row = self._insert_row_at(event.position().toPoint())
        self._clear_indicator()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if rows:
            self.rowsDropped.emit(rows, row)

    def _clear_indicator(self) -> None:
        if self._drop_row != -1:
            self._drop_row = -1
            self.viewport().update()

    def _insert_row_at(self, pos: QPoint) -> int:
        model = self.model()
        count = model.rowCount() if model is not None else 0
        index = self.indexAt(pos)
        if not index.isValid():
            return count
        rect = self.visualRect(index)
        return index.row() + (1 if pos.y() > rect.center().y() else 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_row < 0:
            return
        model = self.model()
        count = model.rowCount() if model is not None else 0
        if count <= 0:
            return
        if self._drop_row < count:
            rect = self.visualRect(model.index(self._drop_row, 0))
            y = rect.top() + 0.5
        else:
            rect = self.visualRect(model.index(count - 1, 0))
            y = rect.bottom() - 0.5

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(ACCENT), 2))
        painter.drawLine(QPointF(10, y), QPointF(self.viewport().width() - 10, y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(QPointF(9, y), 2.6, 2.6)
        painter.end()
