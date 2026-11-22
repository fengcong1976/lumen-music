"""应用数据目录与常量。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

APP_NAME = "Lumen"
ORG_NAME = "LumenAudio"
APP_TITLE = "Lumen 音乐"

# Windows 任务栏分组标识：不设置的话，用 pythonw 启动会被归到 Python 的图标下
APP_ID = "LumenAudio.Lumen.Desktop.1"

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "assets"
ICON_FILE = ASSET_DIR / "icon.ico"
ICON_PNG = ASSET_DIR / "icon.png"
# 公司规范：项目根目录固定放 256×256 图标（关于对话框 / 打包 / 官网共用）
ICON_ROOT_PNG = ROOT / "图标.png"


def data_dir() -> Path:
    """数据目录（歌库缓存、播放列表、设置）。"""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    path = Path(base) if base else Path.home() / ".lumen"
    path.mkdir(parents=True, exist_ok=True)
    return path
