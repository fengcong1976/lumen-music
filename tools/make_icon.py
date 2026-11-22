"""生成应用图标资源：assets/icon.ico（多尺寸）、assets/icon.png，以及预览图。

图标本身由 ui/icons.py 里的矢量绘制生成，没有额外维护的二进制源文件；
改了标志的绘制代码后重跑一次本脚本即可：

    venv\\Scripts\\python.exe tools\\make_icon.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (  # noqa: E402
    QBuffer,
    QByteArray,
    QIODevice,
    QPointF,
    QRectF,
    Qt,
)
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
)

from ui.icons import render_logo  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
PNG_SIZES = {128, 256}          # 小尺寸用 BMP，大尺寸用 PNG（Windows 惯例）
ASSET_DIR = ROOT / "assets"
PREVIEW = ROOT / "docs" / "icon_preview.png"


def _image(side: int) -> QImage:
    return render_logo(side).toImage().convertToFormat(QImage.Format.Format_ARGB32)


def _png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def _bmp_bytes(image: QImage) -> bytes:
    """ICO 内嵌的 DIB：BITMAPINFOHEADER + 倒序 BGRA + AND 掩码。"""
    width, height = image.width(), image.height()
    rows = [bytes(image.constScanLine(y))[: width * 4] for y in range(height - 1, -1, -1)]
    pixels = b"".join(rows)
    mask_row = ((width + 31) // 32) * 4
    mask = b"\x00" * (mask_row * height)
    header = struct.pack(
        "<IiiHHIIiiII",
        40, width, height * 2, 1, 32, 0,
        len(pixels) + len(mask), 0, 0, 0, 0,
    )
    return header + pixels + mask


def build_ico(sizes=SIZES) -> bytes:
    entries: list[bytes] = []
    blobs: list[bytes] = []
    offset = 6 + 16 * len(sizes)
    for side in sizes:
        image = _image(side)
        blob = _png_bytes(image) if side in PNG_SIZES else _bmp_bytes(image)
        dim = 0 if side >= 256 else side
        entries.append(
            struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        )
        blobs.append(blob)
        offset += len(blob)
    return struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(blobs)


def _text(painter: QPainter, rect: QRectF, text: str, color: str, size: int,
          align=Qt.AlignmentFlag.AlignHCenter) -> None:
    if not QFontDatabase.families():
        return          # 离屏平台没有系统字体，跳过文字标签
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(size)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(rect, align | Qt.AlignmentFlag.AlignTop, text)


def write_preview(path: Path, icon: QIcon) -> None:
    """预览图：真实尺寸、放大细节，以及标题栏与深色任务栏下的效果。"""
    canvas = QImage(720, 560, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("#F6F7FB"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    _text(painter, QRectF(24, 24, 400, 22), "Lumen 音乐 · 应用图标", "#2B3040", 14,
          Qt.AlignmentFlag.AlignLeft)

    # 真实尺寸
    x, baseline = 24, 170
    for side in (16, 20, 24, 32, 40, 48, 64):
        painter.drawPixmap(QPointF(x, baseline - side), icon.pixmap(side, side))
        _text(painter, QRectF(x - 14, baseline + 8, side + 28, 16), str(side), "#8A90A2", 10)
        x += side + 22
    painter.drawPixmap(QPointF(x, baseline - 128), icon.pixmap(128, 128))
    _text(painter, QRectF(x - 14, baseline + 8, 156, 16), "128", "#8A90A2", 10)
    x += 150
    painter.drawPixmap(
        QPointF(x, baseline - 128),
        icon.pixmap(256, 256).scaled(
            128, 128,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ),
    )
    _text(painter, QRectF(x - 14, baseline + 8, 156, 16), "256（缩至 128）", "#8A90A2", 10)

    # 小尺寸放大 6 倍，检查细节
    _text(painter, QRectF(24, 206, 340, 18), "小尺寸 6× 放大（16 / 20 / 24 / 32）",
          "#8A90A2", 11, Qt.AlignmentFlag.AlignLeft)
    x = 24
    for side in (16, 20, 24, 32):
        big = side * 6
        painter.drawPixmap(
            QPointF(x, 234),
            icon.pixmap(side, side).scaled(
                big, big,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            ),
        )
        x += big + 22

    # 标题栏模拟（白底）
    painter.fillRect(QRectF(0, 462, 720, 44), QColor("#FFFFFF"))
    painter.setPen(QColor("#E3E6EF"))
    painter.drawLine(QPointF(0, 462), QPointF(720, 462))
    painter.drawPixmap(QPointF(26, 476), icon.pixmap(16, 16))
    _text(painter, QRectF(50, 476, 300, 18), "窗口标题栏（16px）", "#5A6072", 11,
          Qt.AlignmentFlag.AlignLeft)

    # 深色任务栏 / 托盘
    painter.fillRect(QRectF(0, 506, 720, 54), QColor("#202020"))
    _text(painter, QRectF(24, 524, 260, 18), "深色任务栏 / 托盘", "#B9BEC9", 11,
          Qt.AlignmentFlag.AlignLeft)
    x = 300
    for side in (16, 24, 32):
        painter.drawPixmap(QPointF(x, 506 + (54 - side) // 2), icon.pixmap(side, side))
        x += side + 16

    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(path))


def main() -> int:
    QGuiApplication(sys.argv)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    ico_path = ASSET_DIR / "icon.ico"
    ico_path.write_bytes(build_ico())

    png_path = ASSET_DIR / "icon.png"
    render_logo(512).save(str(png_path), "PNG")

    write_preview(PREVIEW, QIcon(str(ico_path)))

    print(f"{ico_path.relative_to(ROOT)}  {ico_path.stat().st_size:>7,} bytes  {len(SIZES)} 个尺寸")
    print(f"{png_path.relative_to(ROOT)}  {png_path.stat().st_size:>7,} bytes  512x512")
    print(f"{PREVIEW.relative_to(ROOT)}  {PREVIEW.stat().st_size:>7,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
