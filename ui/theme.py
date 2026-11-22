"""配色与全局样式表。"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

BG = "#F6F7FB"
CARD = "#FFFFFF"
SIDEBAR = "#FCFCFE"
BORDER = "#EBEDF4"
TEXT = "#191C24"
SUB = "#6E7488"
MUTED = "#9AA0B0"
ACCENT = "#4A5CF0"
ACCENT_DARK = "#3B4BDD"
ACCENT_SOFT = "#EEF0FE"
HOVER = "#F2F4FA"

FONT_FAMILY = "Microsoft YaHei UI"


QSS = f"""
* {{ outline: 0; }}

QMainWindow, QWidget#Root {{ background: {BG}; }}
QWidget {{ color: {TEXT}; }}

QFrame#Sidebar {{
    background: {SIDEBAR};
    border-right: 1px solid {BORDER};
}}
QFrame#LyricsPanel {{
    background: {CARD};
    border-left: 1px solid {BORDER};
}}
QFrame#PlayerBar {{
    background: {CARD};
    border-top: 1px solid {BORDER};
}}
QFrame#Divider {{ background: {BORDER}; }}

QLabel#LogoTitle {{
    font-size: 19px;
    font-weight: 700;
    color: #14171F;
}}
QLabel#LogoSub {{
    font-size: 11px;
    color: {MUTED};
}}
QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 600;
    color: #A8ADBC;
}}
QLabel#ViewTitle {{
    font-size: 21px;
    font-weight: 700;
    color: #14171F;
}}
QLabel#ViewSub {{
    font-size: 12px;
    color: {MUTED};
}}
QLabel#TrackTitle {{
    font-size: 14px;
    font-weight: 600;
    color: #14171F;
}}
QLabel#TrackArtist {{
    font-size: 12px;
    color: #8B90A0;
}}
QLabel#TimeLabel {{
    font-size: 11px;
    color: {MUTED};
}}
QLabel#LyricsHeader {{
    font-size: 13px;
    font-weight: 600;
    color: #14171F;
}}
QLabel#LyricsSource {{
    font-size: 11px;
    color: #B4B9C7;
}}
QLabel#EmptyTitle {{
    font-size: 15px;
    font-weight: 600;
    color: #4C5266;
}}
QLabel#EmptySub {{
    font-size: 12px;
    color: {MUTED};
}}

QPushButton#NavButton {{
    text-align: left;
    padding: 8px 12px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: #4C5266;
    font-size: 13px;
}}
QPushButton#NavButton:hover {{ background: {HOVER}; }}
QPushButton#NavButton:checked {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    font-weight: 600;
}}

QPushButton#GhostButton {{
    background: {CARD};
    border: 1px solid #E6E9F2;
    border-radius: 8px;
    padding: 0 12px;
    color: #4C5266;
    font-size: 12px;
}}
QPushButton#GhostButton:hover {{
    border: 1px solid #C9D0E8;
    background: #F8F9FD;
    color: {TEXT};
}}
QPushButton#GhostButton:pressed {{ background: #F1F3F9; }}

QPushButton#PrimaryButton {{
    background: {ACCENT};
    border: none;
    border-radius: 8px;
    padding: 0 16px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{ background: {ACCENT_DARK}; }}

QPushButton#TinyButton {{
    background: #F1F3FA;
    border: 1px solid #E6E9F2;
    border-radius: 7px;
    color: #4C5266;
    font-size: 11px;
    padding: 0;
}}
QPushButton#TinyButton:hover {{
    background: {ACCENT_SOFT};
    border: 1px solid #C9D0F5;
    color: {ACCENT};
}}
QPushButton#TinyButton:pressed {{ background: #E3E7FA; }}
QPushButton#TinyButton:disabled {{
    background: #F7F8FC;
    border: 1px solid #EFF1F7;
    color: #C3C8D6;
}}

QPushButton#OffsetLabel {{
    background: transparent;
    border: none;
    color: {MUTED};
    font-size: 11px;
    padding: 0 2px;
}}
QPushButton#OffsetLabel:hover {{ color: {ACCENT}; }}
QPushButton#OffsetLabel:disabled {{ color: #C9CEDC; }}

QPushButton#LinkButton {{
    background: transparent;
    border: none;
    color: {ACCENT};
    font-size: 12px;
    padding: 0 2px;
    text-align: left;
}}
QPushButton#LinkButton:hover {{ color: {ACCENT_DARK}; }}

QToolButton#IconButton {{
    border: none;
    background: transparent;
    border-radius: 9px;
}}
QToolButton#IconButton:hover {{ background: {HOVER}; }}
QToolButton#IconButton:pressed {{ background: #E9ECF5; }}
QToolButton#IconButton:checked {{ background: {ACCENT_SOFT}; }}

QToolButton#PlayButton {{
    border: none;
    background: {ACCENT};
    border-radius: 22px;
}}
QToolButton#PlayButton:hover {{ background: {ACCENT_DARK}; }}

QLineEdit#SearchBox {{
    background: {CARD};
    border: 1px solid #E6E9F2;
    border-radius: 17px;
    padding: 0 12px;
    min-height: 34px;
    font-size: 12px;
    color: {TEXT};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT};
}}
QLineEdit#SearchBox:focus {{ border: 1px solid #B9C2FB; }}

QComboBox {{
    background: {CARD};
    border: 1px solid #E6E9F2;
    border-radius: 8px;
    padding: 0 10px;
    min-height: 30px;
    font-size: 12px;
    color: {TEXT};
}}
QComboBox:hover {{ border: 1px solid #C9D0E8; }}
QComboBox:disabled {{ color: #B7BCCB; background: #F7F8FC; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid #E3E7F1;
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT};
    font-size: 12px;
}}

QCheckBox {{
    font-size: 12px;
    color: #4C5266;
    spacing: 7px;
}}
QCheckBox:disabled {{ color: #B7BCCB; }}

QDialog#EqualizerDialog {{
    background: {BG};
    border: 1px solid #E3E7F1;
}}

QLabel#EqTitle {{
    font-size: 17px;
    font-weight: 700;
    color: #14171F;
}}
QLabel#EqSub {{
    font-size: 11px;
    color: {MUTED};
}}
QLabel#EqValue {{
    font-size: 10px;
    color: {SUB};
}}
QLabel#EqBand {{
    font-size: 10px;
    color: {MUTED};
}}

QSlider#EqSlider::groove:vertical {{
    width: 4px;
    background: #E5E8F2;
    border-radius: 2px;
}}
QSlider#EqSlider::add-page:vertical {{
    width: 4px;
    background: transparent;
}}
QSlider#EqSlider::sub-page:vertical {{
    width: 4px;
    background: transparent;
}}
QSlider#EqSlider::handle:vertical {{
    height: 12px;
    margin: 0 -5px;
    border-radius: 6px;
    background: {ACCENT};
}}
QSlider#EqSlider::handle:vertical:hover {{ background: {ACCENT_DARK}; }}
QSlider#EqSlider:disabled::handle:vertical {{ background: #CDD3E4; }}

QListWidget#PlaylistList {{
    background: transparent;
    border: none;
    outline: 0;
}}
QListWidget#PlaylistList::item {{
    padding: 7px 10px;
    border-radius: 8px;
    color: #4C5266;
    font-size: 13px;
}}
QListWidget#PlaylistList::item:hover {{ background: {HOVER}; }}
QListWidget#PlaylistList::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}

QTableView {{
    background: transparent;
    border: none;
    font-size: 13px;
    selection-background-color: transparent;
    alternate-background-color: transparent;
}}
QTableView::item {{
    border-bottom: 1px solid #F3F5FA;
    padding: 0 10px;
    color: #2A2E3A;
}}
QTableView::item:hover {{ background: #F7F8FD; }}
QTableView::item:selected {{ background: {ACCENT_SOFT}; color: #14171F; }}

QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {BORDER};
    color: {MUTED};
    font-size: 11px;
    padding: 9px 10px;
    text-align: left;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: #D9DDE9;
    border-radius: 3px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #C4CADB; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: #D9DDE9; border-radius: 3px; min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QSlider::groove:horizontal {{
    height: 4px;
    background: #E5E8F2;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 11px;
    height: 11px;
    margin: -4px 0;
    border-radius: 5px;
    background: {ACCENT};
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_DARK}; }}

QMenu {{
    background: {CARD};
    border: 1px solid #E3E7F1;
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 12px;
    border-radius: 6px;
    font-size: 12px;
    color: #2A2E3A;
}}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QMenu::item:disabled {{ color: #C0C4D0; }}
QMenu::separator {{ height: 1px; background: #EFF1F7; margin: 5px 8px; }}

QToolTip {{
    background: #23262F;
    color: #FFFFFF;
    border: none;
    padding: 5px 8px;
    border-radius: 6px;
    font-size: 11px;
}}

QLabel#DropHint {{
    background: rgba(250, 251, 254, 242);
    border: 2px dashed rgba(74, 92, 240, 110);
    border-radius: 18px;
    color: {ACCENT_DARK};
    padding: 28px;
}}
"""

PREFERRED_FONTS = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "Segoe UI",
)


def apply_font(app) -> None:
    """挑选一个带中文的界面字体。"""
    try:
        families = set(QFontDatabase.families())
    except Exception:
        families = set()
    for name in PREFERRED_FONTS:
        if name in families:
            font = QFont(name)
            font.setPointSizeF(9.5)
            app.setFont(font)
            return
    font = app.font()
    font.setPointSizeF(9.5)
    app.setFont(font)
