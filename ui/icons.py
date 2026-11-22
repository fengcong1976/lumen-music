"""用 QPainter 绘制的矢量图标，无需外部图片资源。"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from core.paths import ICON_FILE

from .theme import TEXT

_DPR_FALLBACK = 2.0


def _device_ratio() -> float:
    """按当前屏幕的缩放比例渲染，避免高 DPI 下图标发虚（以前硬编码 3.0）。"""
    try:
        app = QGuiApplication.instance()
        if app is not None:
            screen = app.primaryScreen()
            if screen is not None:
                ratio = float(screen.devicePixelRatio())
                if ratio >= 1.0:
                    return ratio
    except Exception:
        pass
    return _DPR_FALLBACK


def _pen(color, width: float = 2.0) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _path(points: list[tuple[float, float]]) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*points[0])
    for x, y in points[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def _speaker(p: QPainter, color: str) -> None:
    path = QPainterPath()
    path.moveTo(4.0, 9.3)
    path.lineTo(7.3, 9.3)
    path.lineTo(11.0, 5.6)
    path.lineTo(11.0, 18.4)
    path.lineTo(7.3, 14.7)
    path.lineTo(4.0, 14.7)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)


def _draw(p: QPainter, name: str, color: str) -> None:
    c = QColor(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)

    if name == "play":
        p.setPen(_pen(color, 2.6))
        p.setBrush(c)
        p.drawPath(_path([(8.4, 5.2), (19.2, 12.0), (8.4, 18.8)]))

    elif name == "pause":
        p.drawRoundedRect(QRectF(6.9, 5.2, 3.7, 13.6), 1.7, 1.7)
        p.drawRoundedRect(QRectF(13.4, 5.2, 3.7, 13.6), 1.7, 1.7)

    elif name == "prev":
        p.drawRoundedRect(QRectF(5.0, 5.6, 2.7, 12.8), 1.2, 1.2)
        p.setPen(_pen(color, 2.6))
        p.drawPath(_path([(19.0, 5.6), (9.5, 12.0), (19.0, 18.4)]))

    elif name == "next":
        p.drawRoundedRect(QRectF(16.3, 5.6, 2.7, 12.8), 1.2, 1.2)
        p.setPen(_pen(color, 2.6))
        p.drawPath(_path([(5.0, 5.6), (14.5, 12.0), (5.0, 18.4)]))

    elif name == "shuffle":
        p.setPen(_pen(color, 1.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.moveTo(3.4, 7.0)
        path.cubicTo(8.4, 7.0, 9.8, 17.0, 14.8, 17.0)
        path.moveTo(3.4, 17.0)
        path.cubicTo(8.4, 17.0, 9.8, 7.0, 14.8, 7.0)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPath(_path([(14.2, 4.5), (18.8, 7.0), (14.2, 9.5)]))
        p.drawPath(_path([(14.2, 14.5), (18.8, 17.0), (14.2, 19.5)]))

    elif name == "repeat":
        p.setPen(_pen(color, 1.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.moveTo(7.0, 5.6)
        path.lineTo(16.0, 5.6)
        path.quadTo(19.6, 5.6, 19.6, 9.2)
        path.lineTo(19.6, 11.0)
        path.moveTo(17.0, 18.4)
        path.lineTo(8.0, 18.4)
        path.quadTo(4.4, 18.4, 4.4, 14.8)
        path.lineTo(4.4, 13.0)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPath(_path([(17.6, 9.8), (21.6, 9.8), (19.6, 13.4)]))
        p.drawPath(_path([(2.4, 14.2), (6.4, 14.2), (4.4, 10.6)]))

    elif name == "repeat_one":
        _draw(p, "repeat", color)
        p.setPen(QColor(color))
        font = QFont()
        font.setPixelSize(9)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(5.5, 7.0, 13.0, 10.0), Qt.AlignmentFlag.AlignCenter, "1")

    elif name in ("volume", "volume_mute"):
        _speaker(p, color)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(color, 1.7))
        if name == "volume":
            p.drawArc(QRectF(11.6, 8.8, 6.0, 6.4), -60 * 16, 120 * 16)
            p.drawArc(QRectF(10.2, 6.4, 9.8, 11.2), -57 * 16, 114 * 16)
        else:
            p.drawLine(QPointF(14.2, 9.6), QPointF(19.6, 15.0))
            p.drawLine(QPointF(19.6, 9.6), QPointF(14.2, 15.0))

    elif name in ("heart", "heart_filled"):
        path = QPainterPath()
        path.moveTo(12.0, 19.6)
        path.cubicTo(4.6, 14.6, 3.0, 10.8, 5.0, 7.9)
        path.cubicTo(7.0, 5.0, 10.6, 5.7, 12.0, 8.4)
        path.cubicTo(13.4, 5.7, 17.0, 5.0, 19.0, 7.9)
        path.cubicTo(21.0, 10.8, 19.4, 14.6, 12.0, 19.6)
        if name == "heart_filled":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
        else:
            p.setPen(_pen(color, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    elif name == "star":
        path = QPainterPath()
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            radius = 8.6 if index % 2 == 0 else 3.8
            point = QPointF(12 + radius * math.cos(angle), 12 + radius * math.sin(angle))
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPath(path)

    elif name == "search":
        p.setPen(_pen(color, 1.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(4.6, 4.6, 11.2, 11.2))
        p.drawLine(QPointF(15.4, 15.4), QPointF(20.0, 20.0))

    elif name == "plus":
        p.setPen(_pen(color, 2.0))
        p.drawLine(QPointF(12.0, 5.6), QPointF(12.0, 18.4))
        p.drawLine(QPointF(5.6, 12.0), QPointF(18.4, 12.0))

    elif name == "folder":
        p.setPen(_pen(color, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.moveTo(3.4, 8.2)
        path.quadTo(3.4, 6.0, 5.6, 6.0)
        path.lineTo(9.0, 6.0)
        path.lineTo(11.0, 8.4)
        path.lineTo(18.4, 8.4)
        path.quadTo(20.6, 8.4, 20.6, 10.6)
        path.lineTo(20.6, 16.8)
        path.quadTo(20.6, 18.6, 18.4, 18.6)
        path.lineTo(5.6, 18.6)
        path.quadTo(3.4, 18.6, 3.4, 16.8)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "clock":
        p.setPen(_pen(color, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(3.8, 3.8, 16.4, 16.4))
        p.drawLine(QPointF(12.0, 7.2), QPointF(12.0, 12.2))
        p.drawLine(QPointF(12.0, 12.2), QPointF(15.6, 14.2))

    elif name == "music":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(4.6, 14.2, 6.0, 4.8))
        p.setPen(_pen(color, 1.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(10.6, 16.6), QPointF(10.6, 6.2))
        path = QPainterPath()
        path.moveTo(10.6, 6.2)
        path.quadTo(15.6, 6.6, 16.0, 10.4)
        p.drawPath(path)

    elif name == "lyrics":
        p.setPen(_pen(color, 1.9))
        p.drawLine(QPointF(3.8, 7.2), QPointF(12.4, 7.2))
        p.drawLine(QPointF(3.8, 12.0), QPointF(12.4, 12.0))
        p.drawLine(QPointF(3.8, 16.8), QPointF(8.2, 16.8))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(13.4, 14.6, 4.4, 3.6))
        p.setPen(_pen(color, 1.6))
        p.drawLine(QPointF(17.6, 16.4), QPointF(17.6, 7.4))
        p.drawLine(QPointF(17.6, 7.4), QPointF(20.8, 9.2))

    elif name == "trash":
        p.setPen(_pen(color, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(4.6, 7.2), QPointF(19.4, 7.2))
        path = QPainterPath()
        path.moveTo(9.4, 7.2)
        path.lineTo(9.7, 4.6)
        path.lineTo(14.3, 4.6)
        path.lineTo(14.6, 7.2)
        p.drawPath(path)
        body = QPainterPath()
        body.moveTo(6.8, 7.2)
        body.lineTo(7.6, 18.2)
        body.quadTo(7.7, 19.6, 9.1, 19.6)
        body.lineTo(14.9, 19.6)
        body.quadTo(16.3, 19.6, 16.4, 18.2)
        body.lineTo(17.2, 7.2)
        p.drawPath(body)

    elif name == "more":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        for x in (6.4, 12.0, 17.6):
            p.drawEllipse(QPointF(x, 12.0), 1.5, 1.5)

    elif name == "close":
        p.setPen(_pen(color, 1.9))
        p.drawLine(QPointF(6.8, 6.8), QPointF(17.2, 17.2))
        p.drawLine(QPointF(17.2, 6.8), QPointF(6.8, 17.2))

    elif name in ("caret_left", "caret_right"):
        p.setPen(_pen(color, 1.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if name == "caret_left":
            path.moveTo(15.0, 5.5)
            path.lineTo(8.5, 12.0)
            path.lineTo(15.0, 18.5)
        else:
            path.moveTo(9.0, 5.5)
            path.lineTo(15.5, 12.0)
            path.lineTo(9.0, 18.5)
        p.drawPath(path)

    elif name == "list":
        p.setPen(_pen(color, 1.9))
        p.drawLine(QPointF(4.4, 7.4), QPointF(19.6, 7.4))
        p.drawLine(QPointF(4.4, 12.0), QPointF(19.6, 12.0))
        p.drawLine(QPointF(4.4, 16.6), QPointF(13.4, 16.6))

    elif name == "sequence":
        # 顺序播放：三行列表 + 向下的箭头（表示播到末尾就停）
        p.setPen(_pen(color, 1.9))
        p.drawLine(QPointF(3.6, 6.8), QPointF(13.4, 6.8))
        p.drawLine(QPointF(3.6, 12.0), QPointF(11.2, 12.0))
        p.drawLine(QPointF(3.6, 17.2), QPointF(8.6, 17.2))
        p.setPen(_pen(color, 2.0))
        p.drawLine(QPointF(17.0, 6.4), QPointF(17.0, 16.4))
        p.drawPath(_path([(14.3, 13.7), (17.0, 17.2), (19.7, 13.7)]))

    elif name == "equalizer":
        p.setPen(_pen(color, 1.9))
        for x, top in ((6.0, 8.0), (12.0, 4.5), (18.0, 10.0)):
            p.drawLine(QPointF(x, top), QPointF(x, 19.0))


def _render(name: str, color: str, size: int) -> QPixmap:
    ratio = _device_ratio()
    side = max(8, int(round(size * ratio)))
    pixmap = QPixmap(side, side)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.scale(size / 24.0, size / 24.0)
    _draw(painter, name, color)
    painter.end()
    return pixmap


def make_icon(name: str, color: str = TEXT, size: int = 20) -> QIcon:
    return QIcon(_render(name, color, size))


def make_pixmap(name: str, color: str = TEXT, size: int = 20) -> QPixmap:
    return _render(name, color, size)


def render_logo(size: int) -> QPixmap:
    """按任意尺寸渲染应用标志（圆角渐变方块 + 播放三角）。"""
    side = max(8, int(size))
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    _logomark(painter, float(side))
    painter.end()
    return pixmap


def _logomark(painter: QPainter, size: float) -> None:
    """在 size × size 的画布上绘制标志，全部按比例计算以适配小尺寸。"""
    rect = QRectF(0.0, 0.0, size, size)
    radius = size * 0.235

    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#6E7DFF"))
    gradient.setColorAt(0.52, QColor("#4A5CF0"))
    gradient.setColorAt(1.0, QColor("#2E38C6"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, radius, radius)

    # 顶部一层很淡的高光，小尺寸下不至于糊成一团
    sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.center().y()))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 58))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(sheen)
    painter.drawRoundedRect(rect, radius, radius)

    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(max(1.1, size * 0.055))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QColor("#FFFFFF"))

    triangle = QPainterPath()
    triangle.moveTo(size * 0.382, size * 0.278)
    triangle.lineTo(size * 0.752, size * 0.5)
    triangle.lineTo(size * 0.382, size * 0.722)
    triangle.closeSubpath()
    painter.drawPath(triangle)


_APP_ICON: QIcon | None = None


def icon_file() -> Path:
    """应用图标文件（assets/icon.ico），不存在时返回空路径。"""
    return ICON_FILE if ICON_FILE.exists() else Path()


def app_icon() -> QIcon:
    """应用图标：优先读取 assets/icon.ico，缺失时用绘制的标志兜底。"""
    global _APP_ICON
    if _APP_ICON is not None:
        return _APP_ICON

    icon = QIcon()
    path = icon_file()
    if path:
        icon = QIcon(str(path))
    if icon.isNull() or not icon.availableSizes():
        icon = QIcon()
        for side in (16, 20, 24, 32, 40, 48, 64, 128, 256):
            icon.addPixmap(render_logo(side))
    _APP_ICON = icon
    return icon

