"""歌词面板：同步高亮 + 平滑滚动 + 点击跳转。"""
from __future__ import annotations

from bisect import bisect_right

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextLayout
from PySide6.QtWidgets import QSizePolicy, QWidget

from core.lyrics import Lyrics

from .theme import ACCENT, MUTED, SUB

LINE_HEIGHT = 40.0
TEXT_MARGIN = 32          # 左右各 16px，留给高亮底色


def wrap_text(text: str, font: QFont, width: int) -> list[str]:
    """按可用宽度折行；中英文都能断，超长单词也强制断开。"""
    if not text:
        return [""]
    limit = max(60, int(width))
    layout = QTextLayout(text, font)
    layout.beginLayout()
    rows: list[str] = []
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(limit)
        start = line.textStart()
        rows.append(text[start:start + line.textLength()].rstrip())
    layout.endLayout()
    return rows or [text]



class LyricsView(QWidget):
    seekRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lyrics: Lyrics | None = None
        self._lines = []
        self._times: list[int] = []
        # 折行后的每句占几行、每句的顶部/高度，长句自动换行后垂直位置依赖这些值
        self._rows: list[list[str]] = []
        self._tops: list[float] = []
        self._heights: list[float] = []
        self._total_height = 0.0
        self._layout_width = -1
        self._layout_current = -2
        self._synced = False
        self._current = -1
        self._target = 0.0
        self._offset = 0.0
        self._position = 0
        self._delay = 0
        self._following = True          # 是否跟着播放进度自动滚动
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        # 手动滚动歌词后，停手 2.2 秒自动回到当前句
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.setInterval(2200)
        self._resume_timer.timeout.connect(self._resume_following)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(180)

    # ---------------------------------------------------------------- 数据
    def set_lyrics(self, lyrics: Lyrics | None, title: str = "") -> None:
        self._lyrics = lyrics
        self._lines = list(lyrics.lines) if lyrics else []
        self._times = [line.time for line in self._lines]
        self._synced = bool(lyrics and not lyrics.plain and self._lines)
        self._current = -1
        # 新歌从 0 开始：不清掉的话，第一帧会按上一首的位置高亮错行
        self._position = 0
        self._following = True
        self._resume_timer.stop()
        self._timer.stop()
        self._layout_width = -1          # 换歌后重新折行
        if self._synced:
            self._target = self._offset = self._target_for(0)
            self._apply_position(force=True)
        else:
            self._target = self._offset = 0.0
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self._synced
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    @property
    def has_synced(self) -> bool:
        return self._synced

    @property
    def following(self) -> bool:
        """是否正在跟随播放进度自动滚动（手动浏览时为 False）。"""
        return self._following

    @property
    def delay(self) -> int:
        """歌词延迟（毫秒）：正值表示歌词整体延后出现。"""
        return self._delay

    def set_delay(self, ms: int) -> None:
        value = int(max(-20000, min(20000, int(ms))))
        if value == self._delay:
            return
        self._delay = value
        self._apply_position(force=True)

    def set_position(self, ms: int) -> None:
        self._position = int(ms)
        self._apply_position()

    def _apply_position(self, force: bool = False) -> None:
        if not self._synced or not self._lines:
            return
        index = bisect_right(self._times, self._position - self._delay) - 1
        if index == self._current and not force:
            return
        self._current = index
        self._target = self._target_for(max(index, 0))
        if self._following:
            if force or not self.isVisible() or abs(self._target - self._offset) > LINE_HEIGHT * 6:
                self._offset = self._target
            self._timer.start()
        self.update()

    # ---------------------------------------------------------------- 布局
    def _ensure_layout(self) -> None:
        """按当前宽度把每句拆成多行，长句不再被省略号截断。"""
        if (
            len(self._rows) == len(self._lines)
            and self._layout_width == self.width()
            and self._layout_current == self._current
        ):
            return

        base = QFont(self.font())
        small = QFont(base)
        small.setPixelSize(14)
        big = QFont(base)
        big.setPixelSize(17)
        big.setWeight(QFont.Weight.DemiBold)
        width = max(60, self.width() - TEXT_MARGIN)

        self._rows = []
        self._tops = []
        self._heights = []
        top = 0.0
        for index, line in enumerate(self._lines):
            font = big if index == self._current else small
            rows = wrap_text(line.text or " ", font, width)
            height = len(rows) * LINE_HEIGHT
            self._rows.append(rows)
            self._tops.append(top)
            self._heights.append(height)
            top += height

        self._total_height = top
        self._layout_width = self.width()
        self._layout_current = self._current

    def _target_for(self, index: int) -> float:
        self._ensure_layout()
        if not self._tops:
            return 0.0
        index = max(0, min(index, len(self._tops) - 1))
        top = self._tops[index] + self._heights[index] / 2.0
        return self.height() / 2.0 - top

    def _offset_bounds(self) -> tuple[float, float]:
        """可滚动范围：不让歌词滚出首句/末句之外。"""
        self._ensure_layout()
        if not self._lines:
            return 0.0, 0.0
        if self._synced:
            high = self._target_for(0)
            low = self._target_for(len(self._lines) - 1)
        else:
            high = 0.0
            low = min(0.0, self.height() - self._total_height)
        if low > high:
            low, high = high, low
        return low, high

    def _resume_following(self) -> None:
        """手动浏览结束，回到当前播放的那一句。"""
        if not self._synced:
            return
        self._following = True
        self._target = self._target_for(max(self._current, 0))
        self._timer.start()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_width = -1          # 宽度变了，重新折行
        if self._synced:
            self._target = self._offset = self._target_for(max(self._current, 0))
        else:
            self._offset = min(self._offset, 0.0)
        self.update()

    # ---------------------------------------------------------------- 动画
    def _tick(self) -> None:
        delta = self._target - self._offset
        if abs(delta) < 0.4:
            self._offset = self._target
            self._timer.stop()
        else:
            self._offset += delta * 0.22
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        width, height = self.width(), self.height()
        if not self._lines:
            self._paint_placeholder(painter, width, height)
            return

        painter.setClipRect(QRectF(0, 0, width, height))
        base_font = QFont(self.font())
        self._ensure_layout()

        for index, line in enumerate(self._lines):
            block = self._heights[index]
            y = self._offset + self._tops[index]
            if y > height or y + block < 0:
                continue

            current = index == self._current
            font = QFont(base_font)
            font.setPixelSize(17 if current else 14)
            font.setWeight(QFont.Weight.DemiBold if current else QFont.Weight.Normal)
            painter.setFont(font)

            if current:
                color = QColor(ACCENT)
                highlight = QRectF(8, y + 4, width - 16, block - 8)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(74, 92, 240, 14))
                painter.drawRoundedRect(highlight, 8, 8)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                distance = abs(y + block / 2 - height / 2) / max(1.0, height / 2)
                alpha = int(max(60, 205 - distance * 150))
                color = QColor(SUB)
                color.setAlpha(alpha)

            painter.setPen(color)
            for row, text in enumerate(self._rows[index]):
                painter.drawText(
                    QRectF(
                        16,
                        y + row * LINE_HEIGHT,
                        width - TEXT_MARGIN,
                        LINE_HEIGHT,
                    ),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    text,
                )

    def _paint_placeholder(self, painter: QPainter, width: int, height: int) -> None:
        font = QFont(self.font())
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRectF(0, height / 2 - 30, width, 24),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "暂无歌词",
        )
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#B4B9C7"))
        painter.drawText(
            QRectF(18, height / 2 + 2, width - 36, 46),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            "把同名 .lrc 文件放在歌曲目录里，就能看到同步歌词",
        )

    # ---------------------------------------------------------------- 交互
    def mousePressEvent(self, event):
        if not self._synced or event.button() != Qt.MouseButton.LeftButton:
            return
        y = event.position().y() - self._offset
        index = -1
        for i, top in enumerate(self._tops):
            if top <= y < top + self._heights[i]:
                index = i
                break
        if 0 <= index < len(self._lines):
            # 歌词有偏移时，跳到「偏移后正好念到这一句」的位置
            self._following = True
            self._resume_timer.stop()
            self.seekRequested.emit(max(0, self._lines[index].time + self._delay))

    def wheelEvent(self, event):
        if not self._lines:
            event.ignore()
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            event.ignore()
            return
        low, high = self._offset_bounds()
        target = max(low, min(high, self._offset + delta * 0.6))
        if abs(target - self._offset) < 0.5:
            event.ignore()      # 已经到头了
            return
        self._offset = target
        if self._synced:
            # 手动浏览时不跟进度；停手一会儿自动回中
            self._following = False
            self._timer.stop()
            self._resume_timer.start()
        event.accept()
        self.update()
