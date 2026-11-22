"""Lumen 音乐 —— 启动入口。

运行：  python main.py
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.library import Library  # noqa: E402
from core.paths import APP_ID, APP_NAME, APP_TITLE, ORG_NAME  # noqa: E402
from core.player import Player  # noqa: E402
from core.single_instance import SingleInstance  # noqa: E402
from ui.icons import app_icon  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import QSS, apply_font  # noqa: E402


def _claim_taskbar_identity() -> None:
    """让 Windows 把本进程当成独立应用（否则任务栏会显示 Python 的图标/分组）。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def main() -> int:
    _claim_taskbar_identity()
    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setApplicationName(APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_TITLE)
    app.setDesktopFileName("lumen")
    app.setWindowIcon(app_icon())
    apply_font(app)
    app.setStyleSheet(QSS)

    # 必须早于建窗口：第二个实例只负责把已有窗口叫出来（并转交文件），然后自己退出。
    instance = SingleInstance()
    if not instance.acquire(sys.argv[1:]):
        return 0

    library = Library()
    player = Player()
    window = MainWindow(library, player)
    instance.activated.connect(window._show_window)
    instance.open_requested.connect(window.open_paths)
    window.show()
    # 窗口先出现，再初始化 VLC 内核：插件缓存缺失时也不会挡住启动。
    QTimer.singleShot(0, player.warm_up)
    if len(sys.argv) > 1:
        window.open_paths(sys.argv[1:])
    code = app.exec()
    instance.release()
    return code


if __name__ == "__main__":
    sys.exit(main())
