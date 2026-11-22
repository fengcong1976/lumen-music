"""主窗口：侧边栏、歌曲列表、播放条、歌词面板。"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QPoint,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.library import Library, ScanWorker, TrackLoader, load_tracks
from core.lyrics import find_lyrics
from core.media_keys import MediaKeyWatcher
from core.metadata import Track, is_audio, open_audio, read_cover_from
from core.paths import APP_TITLE, ORG_NAME, APP_NAME, ICON_PNG, ICON_ROOT_PNG, data_dir
from core.version import VERSION
from core.player import MODE_LABEL, PlayMode, Player
from core.utils import fmt_time, natural_key

from .about_dialog import about_button, show_about
from .equalizer_dialog import EqualizerDialog
from .icons import app_icon, make_icon, make_pixmap
from .lyrics_view import LyricsView
from .models import SongModel, TrackFilterProxy
from .theme import ACCENT, MUTED, SUB
from .widgets import AlbumCover, ClickSlider, SongTable, icon_button


class MainWindow(QMainWindow):
    VIEW_ALL = "all"
    VIEW_RECENT = "recent"
    VIEW_FAVORITES = "favorites"
    VIEW_PLAYLIST = "playlist"

    DROP_SYNC_LIMIT = 40      # 少于这个数量就同步读标签，超过则放到后台线程

    def __init__(self, library: Library, player: Player, parent=None):
        super().__init__(parent)
        self.library = library
        self.player = player
        # 显式 INI 格式：设置落 %APPDATA%\LumenAudio\Lumen\Lumen.ini，不写注册表（微软商店合规）
        self.settings = QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, ORG_NAME, APP_NAME
        )

        self._nav_buttons: list[QPushButton] = []
        self._nav_map: dict[QPushButton, str] = {}
        self._view = self.VIEW_ALL
        self._playlist_id = ""
        self._scan_worker: ScanWorker | None = None
        self._current: Track | None = None
        self._seeking = False
        self._syncing_slider = False
        self._muted = False
        self._restore_volume = 72
        self._cover_cache: dict[str, tuple[tuple[float, int], bytes | None, object]] = {}
        self._offsets: dict[str, int] = {}
        self._orders: dict[str, list[str]] = {}
        self._tray: QSystemTrayIcon | None = None
        self._tray_enabled = True
        self._tray_hint_shown = False
        self._quitting = False
        self._media_keys = MediaKeyWatcher(self)

        self._drop_loader: TrackLoader | None = None
        self._rescan_pending: bool = False

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._update_header)

        # 音量每拖一格写一次 QSettings 太频繁，攒 400ms 再落盘。
        self._volume_save_timer = QTimer(self)
        self._volume_save_timer.setSingleShot(True)
        self._volume_save_timer.setInterval(400)
        self._volume_save_timer.timeout.connect(self._save_volume)

        self._build_ui()
        self._connect()
        self._restore_state()
        self.equalizer_dialog = EqualizerDialog(self.player, self.settings, self)
        self._setup_tray()
        self._setup_media_keys()
        self._refresh_playlist_widget()
        self.select_view(self.VIEW_ALL)
        QTimer.singleShot(500, self._auto_scan)

    # ================================================================ 构建界面
    def _build_ui(self) -> None:
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1200, 800)
        self.setMinimumSize(1000, 660)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_main(), 1)
        self.lyrics_panel = self._build_lyrics_panel()
        body.addWidget(self.lyrics_panel)

        outer.addLayout(body, 1)
        outer.addWidget(self._build_player_bar())

        # 拖拽时的提示浮层（不接收鼠标事件，避免影响放置目标判定）
        self.drop_hint = QLabel(root)
        self.drop_hint.setObjectName("DropHint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setTextFormat(Qt.TextFormat.RichText)
        self.drop_hint.setText(
            "<div style='font-size:19px; font-weight:600;'>松开鼠标，开始播放</div>"
            "<div style='font-size:12px; color:#7C82A0; margin-top:8px;'>"
            "文件或整个文件夹都行，多首会自动建成播放列表</div>"
        )
        self.drop_hint.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.drop_hint.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_drop_hint()

    def _place_drop_hint(self) -> None:
        hint = getattr(self, "drop_hint", None)
        root = self.centralWidget()
        if hint is None or root is None:
            return
        hint.setGeometry(root.rect().adjusted(16, 16, -16, -16))

    # ---------------------------------------------------------------- 侧边栏
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(228)

        layout = QVBoxLayout(side)
        layout.setContentsMargins(14, 20, 14, 14)
        layout.setSpacing(3)

        # 品牌行：标题 + 副标题在左，标准「关于」按钮在右
        brand = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Lumen")
        title.setObjectName("LogoTitle")
        subtitle = QLabel("本地音乐播放器")
        subtitle.setObjectName("LogoSub")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        brand.addLayout(titles, 1)
        self.btn_about = about_button(APP_TITLE, version=VERSION)
        self.btn_about.setObjectName("TinyButton")
        self.btn_about.setFixedSize(48, 26)
        self.btn_about.setCursor(Qt.CursorShape.PointingHandCursor)
        brand.addWidget(self.btn_about, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(brand)
        layout.addSpacing(18)

        self.nav_all = self._make_nav_button("music", "全部歌曲", self.VIEW_ALL)
        self.nav_recent = self._make_nav_button("clock", "最近添加", self.VIEW_RECENT)
        self.nav_fav = self._make_nav_button("heart", "我喜欢的音乐", self.VIEW_FAVORITES)
        for button in self._nav_buttons:
            layout.addWidget(button)

        layout.addSpacing(16)
        header = QHBoxLayout()
        header.setContentsMargins(10, 0, 2, 0)
        section = QLabel("播放列表")
        section.setObjectName("SectionLabel")
        self.btn_playlist_add = icon_button("plus", SUB, 14, 26, "新建播放列表")
        header.addWidget(section)
        header.addStretch(1)
        header.addWidget(self.btn_playlist_add)
        layout.addLayout(header)

        self.playlist_list = QListWidget()
        self.playlist_list.setObjectName("PlaylistList")
        self.playlist_list.setFrameShape(QFrame.Shape.NoFrame)
        self.playlist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.playlist_list.setIconSize(QSize(14, 14))
        layout.addWidget(self.playlist_list, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.btn_add_folder = QPushButton(" 添加音乐文件夹")
        self.btn_add_folder.setObjectName("GhostButton")
        self.btn_add_folder.setIcon(make_icon("folder", SUB, 15))
        self.btn_add_folder.setIconSize(QSize(15, 15))
        self.btn_add_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_folder.setFixedHeight(34)
        self.btn_more = icon_button("more", SUB, 16, 34, "更多")
        bottom.addWidget(self.btn_add_folder, 1)
        bottom.addWidget(self.btn_more)
        layout.addLayout(bottom)
        return side

    def _make_nav_button(self, icon_name: str, text: str, view: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(36)
        button.setIconSize(QSize(16, 16))
        icon = QIcon()
        icon.addPixmap(make_pixmap(icon_name, SUB, 16),
                       QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(make_pixmap(icon_name, ACCENT, 16),
                       QIcon.Mode.Normal, QIcon.State.On)
        button.setIcon(icon)
        button.clicked.connect(lambda: self.select_view(view))
        self._nav_buttons.append(button)
        self._nav_map[button] = view
        return button

    # ---------------------------------------------------------------- 主区域
    def _build_main(self) -> QWidget:
        main = QWidget()
        main.setObjectName("Content")
        layout = QVBoxLayout(main)
        layout.setContentsMargins(24, 20, 24, 0)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.view_title = QLabel("全部歌曲")
        self.view_title.setObjectName("ViewTitle")
        self.view_sub = QLabel("")
        self.view_sub.setObjectName("ViewSub")
        titles.addWidget(self.view_title)
        titles.addWidget(self.view_sub)
        header.addLayout(titles)
        header.addStretch(1)

        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText("搜索歌名、艺术家、专辑")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(250)
        self.search.setMinimumHeight(34)
        self.search.addAction(make_icon("search", MUTED, 14),
                              QLineEdit.ActionPosition.LeadingPosition)

        # 搜索有结果时才出现：把当前搜索结果整批存成一个播放列表
        self.btn_save_search = QPushButton(" 存为歌单")
        self.btn_save_search.setObjectName("GhostButton")
        self.btn_save_search.setIcon(make_icon("plus", SUB, 14))
        self.btn_save_search.setIconSize(QSize(14, 14))
        self.btn_save_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_search.setFixedHeight(34)
        self.btn_save_search.setVisible(False)
        self.btn_save_search.clicked.connect(self._save_search_playlist)

        self.btn_play_all = QPushButton(" 播放全部")
        self.btn_play_all.setObjectName("PrimaryButton")
        self.btn_play_all.setIcon(make_icon("play", "#FFFFFF", 13))
        self.btn_play_all.setIconSize(QSize(13, 13))
        self.btn_play_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_all.setFixedHeight(34)

        header.addWidget(self.search)
        header.addWidget(self.btn_save_search)
        header.addWidget(self.btn_play_all)
        layout.addLayout(header)

        self.model = SongModel(self.library, self)
        self.proxy = TrackFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = SongTable()
        self.table.setObjectName("SongTable")
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(True)
        self.table.setIconSize(QSize(13, 13))
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.model.set_base_font(self.table.font())

        head = self.table.horizontalHeader()
        head.setHighlightSections(False)
        head.setSectionsClickable(True)
        head.setSortIndicatorShown(True)
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        head.resizeSection(0, 52)
        self._index_width_manual = False
        self._index_fitting = False
        head.sectionResized.connect(self._on_section_resized)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        head.resizeSection(2, 170)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        head.resizeSection(3, 190)
        head.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        head.resizeSection(4, 72)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self._build_empty_page())
        layout.addWidget(self.stack, 1)

        self.proxy.sort(-1)
        head.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        return main

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon = QLabel()
        icon.setPixmap(make_pixmap("music", "#C9CEDD", 44))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.empty_title = QLabel("音乐库还是空的")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.empty_sub = QLabel("添加一个存放音乐的文件夹，就能开始管理播放列表")
        self.empty_sub.setObjectName("EmptySub")
        self.empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_empty_add = QPushButton(" 添加音乐文件夹")
        self.btn_empty_add.setObjectName("PrimaryButton")
        self.btn_empty_add.setIcon(make_icon("folder", "#FFFFFF", 14))
        self.btn_empty_add.setIconSize(QSize(14, 14))
        self.btn_empty_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_empty_add.setFixedSize(150, 36)
        self.btn_empty_add.clicked.connect(self._choose_folder)

        layout.addWidget(icon)
        layout.addWidget(self.empty_title)
        layout.addWidget(self.empty_sub)
        layout.addSpacing(8)
        layout.addWidget(self.btn_empty_add, 0, Qt.AlignmentFlag.AlignHCenter)
        return page

    # ---------------------------------------------------------------- 歌词面板
    def _build_lyrics_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("LyricsPanel")
        panel.setFixedWidth(304)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        label = QLabel("歌词")
        label.setObjectName("LyricsHeader")
        self.lyrics_source = QLabel("")
        self.lyrics_source.setObjectName("LyricsSource")
        self.btn_close_lyrics = icon_button("close", MUTED, 13, 26, "隐藏歌词")
        head.addWidget(label)
        head.addStretch(1)
        head.addWidget(self.lyrics_source)
        head.addWidget(self.btn_close_lyrics)
        layout.addLayout(head)

        self.cover_big = AlbumCover(268, 14)
        layout.addWidget(self.cover_big, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lyrics = LyricsView()
        layout.addWidget(self.lyrics, 1)

        # 歌词偏移微调：-0.5s / +0.5s，中间显示当前偏移并可点击归零
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.btn_offset_minus = self._offset_button("-0.5s", "歌词出现得更早 0.5 秒")
        self.btn_offset_plus = self._offset_button("+0.5s", "歌词出现得更晚 0.5 秒")
        self.btn_offset_label = QPushButton("偏移 0.0s")
        self.btn_offset_label.setObjectName("OffsetLabel")
        self.btn_offset_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_offset_label.setFixedHeight(24)
        self.btn_offset_label.setMinimumWidth(74)
        self.btn_offset_label.setToolTip("歌词偏移，点击归零")
        footer.addStretch(1)
        footer.addWidget(self.btn_offset_minus)
        footer.addWidget(self.btn_offset_label)
        footer.addWidget(self.btn_offset_plus)
        footer.addStretch(1)
        layout.addLayout(footer)
        return panel

    @staticmethod
    def _offset_button(text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("TinyButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip)
        button.setFixedSize(54, 24)
        return button

    # ---------------------------------------------------------------- 播放条
    def _build_player_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("PlayerBar")
        bar.setFixedHeight(98)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        # 左侧：封面 + 曲目信息
        info = QWidget()
        info.setFixedWidth(280)
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(12)

        self.cover_small = AlbumCover(58, 10)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        self.track_title = QLabel("未在播放")
        self.track_title.setObjectName("TrackTitle")
        self.track_artist = QLabel("选一首歌开始吧")
        self.track_artist.setObjectName("TrackArtist")
        for label in (self.track_title, self.track_artist):
            label.setFixedWidth(208)
        texts.addWidget(self.track_title)
        texts.addWidget(self.track_artist)
        info_layout.addWidget(self.cover_small)
        info_layout.addLayout(texts)

        # 中间：控制 + 进度
        center = QWidget()
        center.setFixedWidth(460)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.setSpacing(14)
        self.btn_mode = icon_button("repeat", ACCENT, 17, 32, "播放模式")
        self.btn_prev = icon_button("prev", "#3A3F4D", 18, 32, "上一首")
        self.btn_play = QToolButton()
        self.btn_play.setObjectName("PlayButton")
        self.btn_play.setFixedSize(44, 44)
        self.btn_play.setIcon(make_icon("play", "#FFFFFF", 20))
        self.btn_play.setIconSize(QSize(20, 20))
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.setToolTip("播放 / 暂停（空格）")
        self.btn_next = icon_button("next", "#3A3F4D", 18, 32, "下一首")
        self.btn_fav = icon_button("heart", SUB, 18, 32, "收藏当前歌曲", checkable=True)

        controls.addStretch(1)
        for widget in (self.btn_mode, self.btn_prev, self.btn_play,
                       self.btn_next, self.btn_fav):
            controls.addWidget(widget)
        controls.addStretch(1)

        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.time_now = QLabel("0:00")
        self.time_now.setObjectName("TimeLabel")
        self.time_now.setFixedWidth(38)
        self.time_now.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider = ClickSlider()
        self.slider.setRange(0, 1)
        self.slider.setToolTip("拖动或点击跳转播放位置")
        self.time_total = QLabel("0:00")
        self.time_total.setObjectName("TimeLabel")
        self.time_total.setFixedWidth(38)
        progress.addWidget(self.time_now)
        progress.addWidget(self.slider, 1)
        progress.addWidget(self.time_total)

        center_layout.addStretch(1)
        center_layout.addLayout(controls)
        center_layout.addLayout(progress)
        center_layout.addStretch(1)
        layout.addWidget(info)
        layout.addStretch(1)
        layout.addWidget(center)
        layout.addStretch(1)

        # 右侧：音量 + 歌词开关
        right = QWidget()
        right.setFixedWidth(206)
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.btn_eq = icon_button("equalizer", SUB, 18, 32, "音效 · 均衡器")
        self.btn_mute = icon_button("volume", SUB, 18, 30, "静音")
        self.volume_slider = ClickSlider()
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(78)
        self.volume_slider.setToolTip("音量")
        self.btn_lyrics = icon_button("lyrics", SUB, 18, 32, "显示 / 隐藏歌词", checkable=True)
        right_layout.addStretch(1)
        right_layout.addWidget(self.btn_eq)
        right_layout.addWidget(self.btn_mute)
        right_layout.addWidget(self.volume_slider)
        right_layout.addWidget(self.btn_lyrics)
        layout.addWidget(right)
        return bar

    # ================================================================ 信号
    def _connect(self) -> None:
        self.library.changed.connect(self._on_library_changed)
        self.library.saveFailed.connect(self._flash)

        self.player.trackChanged.connect(self._on_track_changed)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.stateChanged.connect(self._on_state)
        self.player.modeChanged.connect(self._on_mode_changed)
        self.player.errorRaised.connect(self._flash)

        self.btn_play.clicked.connect(self.player.toggle)
        self.btn_prev.clicked.connect(self.player.previous)
        self.btn_next.clicked.connect(lambda: self.player.next(manual=True))
        self.btn_mode.clicked.connect(self.player.cycle_mode)
        self.btn_fav.clicked.connect(self._toggle_favorite_current)
        self.btn_lyrics.clicked.connect(self._toggle_lyrics_panel)
        self.btn_close_lyrics.clicked.connect(self._toggle_lyrics_panel)

        self.slider.sliderPressed.connect(self._begin_seek)
        self.slider.sliderReleased.connect(self._end_seek)
        self.slider.valueChanged.connect(self._on_slider_value)

        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.btn_mute.clicked.connect(self._toggle_mute)
        self.btn_eq.clicked.connect(self._show_equalizer)

        self.search.textChanged.connect(self._on_search)
        self.table.doubleClicked.connect(self._on_row_activated)
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        self.table.rowsDropped.connect(self._on_rows_dropped)
        self.playlist_list.itemClicked.connect(self._on_playlist_clicked)
        self.playlist_list.customContextMenuRequested.connect(self._show_playlist_menu)

        self.btn_add_folder.clicked.connect(self._choose_folder)
        self.btn_play_all.clicked.connect(self._play_all)
        self.btn_playlist_add.clicked.connect(lambda: self._create_playlist())
        self.btn_more.clicked.connect(self._show_more_menu)
        self.lyrics.seekRequested.connect(self.player.seek)

        self.btn_offset_minus.clicked.connect(lambda: self._nudge_offset(-500))
        self.btn_offset_plus.clicked.connect(lambda: self._nudge_offset(500))
        self.btn_offset_label.clicked.connect(lambda: self._set_offset(0))

        shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut.activated.connect(self._focus_search)

    # ================================================================ 状态
    def _restore_state(self) -> None:
        geometry = self.settings.value("ui/geometry")
        if geometry:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass

        try:
            volume = int(self.settings.value("audio/volume", 72))
        except (TypeError, ValueError):
            volume = 72
        self._restore_volume = max(0, min(100, volume))
        self.volume_slider.setValue(self._restore_volume)

        raw_mode = self.settings.value("audio/mode", PlayMode.LOOP_ALL.value)
        try:
            mode = PlayMode(str(raw_mode))
        except ValueError:
            mode = PlayMode.LOOP_ALL
        self.player.mode = mode
        self._on_mode_changed(mode)

        raw_lyrics = self.settings.value("ui/lyrics", True)
        visible = self._as_bool(raw_lyrics, True)
        self.lyrics_panel.setVisible(visible)
        self.btn_lyrics.setChecked(visible)

        self._tray_enabled = self._as_bool(self.settings.value("ui/tray", True), True)

        raw_offsets = self.settings.value("lyrics/offsets", {})
        if isinstance(raw_offsets, dict):
            for key, value in raw_offsets.items():
                try:
                    self._offsets[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
        self._update_offset_label()

    @staticmethod
    def _as_bool(value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _save_state(self) -> None:
        self.settings.setValue("ui/geometry", self.saveGeometry())
        # 用 isHidden 而非 isVisible：窗口隐藏到托盘时也能存对
        self.settings.setValue("ui/lyrics", not self.lyrics_panel.isHidden())
        self.settings.setValue("audio/volume", self.volume_slider.value())
        self.settings.setValue("audio/mode", self.player.mode.value)
        self.settings.setValue("ui/tray", self._tray_enabled)
        self._persist_offsets()
        self.settings.sync()

    def closeEvent(self, event) -> None:
        if self._tray is not None and self._tray_enabled and not self._quitting:
            # 关闭 = 缩到托盘继续播放
            event.ignore()
            self._save_state()
            self._hide_to_tray()
            return
        self._save_state()
        self._teardown()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._tray is not None
            and self._tray_enabled
        ):
            QTimer.singleShot(0, self._hide_to_tray)
        super().changeEvent(event)

    def _teardown(self) -> None:
        self._media_keys.stop()
        if self._tray is not None:
            self._tray.hide()
            self._tray = None
        self._stop_thread(self._drop_loader)
        self._stop_thread(self._scan_worker)
        self.player.stop()

    @staticmethod
    def _stop_thread(thread, timeout: int = 3000) -> None:
        """让后台线程停下；卡在慢速磁盘/网络路径上时不再无限等，也不再崩在析构里。"""
        if thread is None:
            return
        request_stop = getattr(thread, "request_stop", None)
        if callable(request_stop):
            request_stop()
        if not thread.isRunning():
            return
        if thread.wait(timeout):
            return
        thread.terminate()
        thread.wait(1000)

    # ================================================================ 托盘
    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip(APP_TITLE)

        menu = QMenu(self)
        show_action = menu.addAction("显示主界面")
        show_action.triggered.connect(self._show_window)
        menu.addSeparator()
        self._tray_play = menu.addAction(make_icon("play", SUB, 14), "播放")
        self._tray_play.triggered.connect(self.player.toggle)
        self._tray_prev = menu.addAction(make_icon("prev", SUB, 14), "上一首")
        self._tray_prev.triggered.connect(self.player.previous)
        self._tray_next = menu.addAction(make_icon("next", SUB, 14), "下一首")
        self._tray_next.triggered.connect(lambda: self.player.next(manual=True))
        menu.addSeparator()
        self._tray_toggle = menu.addAction("最小化到托盘")
        self._tray_toggle.setCheckable(True)
        self._tray_toggle.setChecked(self._tray_enabled)
        self._tray_toggle.toggled.connect(self._set_tray_enabled)
        quit_action = menu.addAction("退出 Lumen")
        quit_action.triggered.connect(self._quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()

        self._tray = tray
        self._tray_menu = menu

    def _on_tray_activated(self, reason) -> None:
        # 双击时 Windows 先发 Trigger 再发 DoubleClick，两条路径都只做「显示」，
        # 不能像以前那样在 DoubleClick 里再把窗口藏起来（否则双击等于没反应）。
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _hide_to_tray(self) -> None:
        if self._tray is None:
            return
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self._tray.showMessage(
                APP_TITLE,
                "Lumen 仍在后台运行，双击托盘图标可恢复窗口。",
                app_icon(),
                4000,
            )

    def _set_tray_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._tray_enabled:
            return
        self._tray_enabled = enabled
        self.settings.setValue("ui/tray", enabled)
        if hasattr(self, "_tray_toggle"):
            self._tray_toggle.blockSignals(True)
            self._tray_toggle.setChecked(enabled)
            self._tray_toggle.blockSignals(False)
        if not enabled and not self.isVisible():
            self._show_window()
        self._flash("关闭窗口时保留在托盘" if enabled else "关闭窗口将退出程序")

    def _quit(self) -> None:
        self._quitting = True
        self.close()

    # ================================================================ 媒体键
    def _setup_media_keys(self) -> None:
        self._media_keys.playPause.connect(self.player.toggle)
        self._media_keys.nextPressed.connect(lambda: self.player.next(manual=True))
        self._media_keys.previousPressed.connect(self.player.previous)
        self._media_keys.stopPressed.connect(self._stop_playback)
        self._media_keys.start()

    def _stop_playback(self) -> None:
        self.player.stop()
        self._flash("已停止播放")

    # ================================================================ 视图
    def _current_tracks(self) -> list[Track]:
        if self._view == self.VIEW_RECENT:
            return self.library.recent_tracks()
        if self._view == self.VIEW_FAVORITES:
            return self.library.favorite_tracks()
        if self._view == self.VIEW_PLAYLIST:
            return self.library.playlist_tracks(self._playlist_id)
        return self.library.all_tracks()

    def _view_key(self) -> str:
        if self._view == self.VIEW_PLAYLIST:
            return f"playlist:{self._playlist_id}"
        return self._view

    def _ordered_tracks(self, tracks: list[Track]) -> list[Track]:
        """套用本次会话里拖动过的顺序（新增的歌排在后面）。"""
        order = self._orders.get(self._view_key())
        if not order or not tracks:
            return tracks
        by_path = {track.path: track for track in tracks}
        ordered = [by_path.pop(path) for path in order if path in by_path]
        ordered.extend(by_path.values())
        return ordered

    def select_view(self, view: str, playlist_id: str = "") -> None:
        self._view = view
        self._playlist_id = playlist_id
        self._reload_tracks()

        for button in self._nav_buttons:
            button.setChecked(self._nav_map.get(button) == view)
        if view == self.VIEW_PLAYLIST:
            self._select_playlist_item(playlist_id)
        else:
            self.playlist_list.clearSelection()

        self._update_header()
        self._sync_stack()

    def _reload_tracks(self, keep_state: bool = False) -> None:
        tracks = self._ordered_tracks(self._current_tracks())
        if keep_state:
            self.model.sync_tracks(tracks)
        else:
            self.model.set_tracks(tracks)
        if self._current is not None:
            self.model.set_current(self._current.path)
        self._fit_index_column()

    def _fit_index_column(self) -> None:
        """序号列按曲目数量的位数自适应；用户手动拖过之后不再自动改。"""
        if getattr(self, "_index_width_manual", False):
            return
        rows = max(self.model.rowCount(), 1)
        digits = len(str(rows))
        width = max(52, self.table.fontMetrics().horizontalAdvance("0" * digits) + 32)
        head = self.table.horizontalHeader()
        if head.sectionSize(0) != width:
            self._index_fitting = True
            head.resizeSection(0, width)
            self._index_fitting = False

    def _on_section_resized(self, section: int, old: int, new: int) -> None:
        """用户拖动表头后记住手动宽度，后续刷新不再覆盖。"""
        if section == 0 and not getattr(self, "_index_fitting", False):
            self._index_width_manual = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 样式表在显示后才完全生效，这里再按真实字体校准一次。
        QTimer.singleShot(0, self._fit_index_column)

    def _update_header(self) -> None:
        if self._view == self.VIEW_RECENT:
            title = "最近添加"
        elif self._view == self.VIEW_FAVORITES:
            title = "我喜欢的音乐"
        elif self._view == self.VIEW_PLAYLIST:
            playlist = self.library.playlist(self._playlist_id)
            title = playlist.name if playlist else "播放列表"
        else:
            title = "全部歌曲"
        self.view_title.setText(title)

        query = self.search.text().strip()
        if query:
            found = self.proxy.rowCount()
            self.view_sub.setText(f"“{query}” 找到 {found} 首")
            self.btn_save_search.setVisible(found > 0)
            self.btn_save_search.setToolTip(
                f"把当前搜索结果的 {found} 首歌曲保存成播放列表"
            )
            return

        self.btn_save_search.setVisible(False)

        count = len(self._current_tracks())
        if self._view == self.VIEW_ALL:
            self.view_sub.setText(
                f"{count} 首歌曲 · {len(self.library.folders)} 个文件夹"
            )
        elif self._view == self.VIEW_RECENT:
            self.view_sub.setText(f"{count} 首 · 按入库时间排序")
        else:
            self.view_sub.setText(f"{count} 首歌曲")

    def _sync_stack(self) -> None:
        visible = self.proxy.rowCount()
        if visible:
            self.stack.setCurrentWidget(self.table)
        else:
            self._update_empty_state()
            self.stack.setCurrentWidget(self.stack.widget(1))

    def _update_empty_state(self) -> None:
        query = self.search.text().strip()
        if query:
            self.empty_title.setText("没有找到匹配的歌曲")
            self.empty_sub.setText("换个歌名、艺术家或专辑关键词试试")
            self.btn_empty_add.setVisible(False)
        elif not self.library.tracks:
            self.empty_title.setText("音乐库还是空的")
            self.empty_sub.setText("添加一个存放音乐的文件夹，就能开始管理播放列表")
            self.btn_empty_add.setVisible(True)
        elif self._view == self.VIEW_FAVORITES:
            self.empty_title.setText("还没有喜欢的歌曲")
            self.empty_sub.setText("点击播放条上的爱心，收藏正在播放的歌曲")
            self.btn_empty_add.setVisible(False)
        elif self._view == self.VIEW_PLAYLIST:
            self.empty_title.setText("这个列表还没有歌曲")
            self.empty_sub.setText("在歌曲上右键 → 添加到播放列表")
            self.btn_empty_add.setVisible(False)
        else:
            self.empty_title.setText("这里还没有歌曲")
            self.empty_sub.setText("试试添加更多音乐文件夹")
            self.btn_empty_add.setVisible(not self.library.tracks)

    def _refresh_playlist_widget(self) -> None:
        self.playlist_list.blockSignals(True)
        self.playlist_list.clear()
        for playlist in self.library.playlists:
            item = QListWidgetItem(make_icon("list", SUB, 14), playlist.name)
            item.setData(Qt.ItemDataRole.UserRole, playlist.id)
            item.setToolTip(f"{self.library.count_of(playlist.id)} 首歌曲")
            self.playlist_list.addItem(item)
        self.playlist_list.blockSignals(False)
        if self._view == self.VIEW_PLAYLIST:
            self._select_playlist_item(self._playlist_id)

    def _select_playlist_item(self, playlist_id: str) -> None:
        for row in range(self.playlist_list.count()):
            item = self.playlist_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == playlist_id:
                self.playlist_list.setCurrentItem(item)
                return

    def _on_library_changed(self) -> None:
        self._refresh_playlist_widget()
        # 视图没变、只是库内容变了：尽量只刷新有变化的行，
        # 别因为加了一首歌就把滚动位置和已选中的行全清掉。
        self._reload_tracks(keep_state=True)
        self._update_header()
        self._sync_stack()

    def _on_playlist_clicked(self, item: QListWidgetItem) -> None:
        playlist_id = item.data(Qt.ItemDataRole.UserRole)
        if playlist_id:
            self.select_view(self.VIEW_PLAYLIST, str(playlist_id))

    # ================================================================ 播放
    def _visible_tracks(self) -> list[Track]:
        tracks: list[Track] = []
        for row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(row, 0))
            track = self.model.track_at(source.row())
            if track is not None:
                tracks.append(track)
        return tracks

    def _on_row_activated(self, index) -> None:
        tracks = self._visible_tracks()
        if not tracks:
            return
        self.player.play_queue(tracks, max(0, min(index.row(), len(tracks) - 1)))

    def _track_at_proxy_row(self, row: int) -> Track | None:
        if not 0 <= row < self.proxy.rowCount():
            return None
        source = self.proxy.mapToSource(self.proxy.index(row, 0))
        return self.model.track_at(source.row())

    def _on_rows_dropped(self, rows: list[int], drop_row: int) -> None:
        """拖动调整播放顺序：落点上方那首歌作为锚点。"""
        total = self.proxy.rowCount()
        if total <= 1:
            return
        rows = sorted({int(row) for row in rows if 0 <= int(row) < total})
        if not rows:
            return
        drop = max(0, min(int(drop_row), total))

        anchor_path = ""
        for row in range(drop - 1, -1, -1):
            if row in rows:
                continue
            track = self._track_at_proxy_row(row)
            if track is not None:
                anchor_path = track.path
                break

        paths = [
            track.path
            for track in (self._track_at_proxy_row(row) for row in rows)
            if track is not None
        ]
        if not paths:
            return

        # 有列排序时，视觉顺序与模型顺序不同，先退回自定义顺序
        had_sort = self.table.horizontalHeader().sortIndicatorSection() >= 0
        if had_sort:
            self.proxy.sort(-1)
            self.table.horizontalHeader().setSortIndicator(
                -1, Qt.SortOrder.AscendingOrder
            )

        moved = self.model.move_paths(paths, anchor_path or None)
        if self._view == self.VIEW_PLAYLIST:
            # 播放列表里的顺序会保存下来
            self.library.move_in_playlist(
                self._playlist_id, paths, anchor_path or None
            )
        self._select_paths(paths)
        if not moved:
            return
        self._orders[self._view_key()] = [
            track.path
            for track in (self.model.track_at(row) for row in range(self.model.rowCount()))
            if track is not None
        ]
        queued = self.player.sync_queue_order(self._visible_tracks())
        prefix = "已取消列排序 · " if had_sort else ""
        if queued:
            self._flash(f"{prefix}播放顺序已更新")
        else:
            self._flash(f"{prefix}已调整顺序")

    def _select_paths(self, paths: list[str]) -> None:
        selection = self.table.selectionModel()
        if selection is None:
            return
        wanted = set(paths)
        selection.clearSelection()
        first = None
        for row in range(self.proxy.rowCount()):
            track = self._track_at_proxy_row(row)
            if track is None or track.path not in wanted:
                continue
            index = self.proxy.index(row, 0)
            selection.select(
                index,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            if first is None:
                first = index
        if first is not None:
            self.table.scrollTo(first)

    def _play_all(self) -> None:
        tracks = self._visible_tracks()
        if not tracks:
            self._flash("列表里还没有歌曲")
            return
        self.player.play_queue(tracks, 0)

    def _on_track_changed(self, track) -> None:
        if track is None:
            return
        self._current = track
        self.model.set_current(track.path)

        metrics = QFontMetrics(self.track_title.font())
        self.track_title.setText(
            metrics.elidedText(track.title, Qt.TextElideMode.ElideRight, 206)
        )
        self.track_artist.setText(
            metrics.elidedText(track.artist, Qt.TextElideMode.ElideRight, 206)
        )
        self.track_title.setToolTip(f"{track.title}\n{track.artist}\n{track.path}")

        cover, lyrics = self._load_extras(track)
        seed = sum(ord(char) for char in track.title) or 7
        self.cover_small.set_cover(cover, seed)
        self.cover_big.set_cover(cover, seed)

        self.lyrics.set_lyrics(lyrics, track.title)
        self.lyrics.set_delay(self._offsets.get(track.path, 0))
        self._update_offset_label()
        self.lyrics_source.setText(self._lyrics_source_text(lyrics))

        self.btn_fav.setChecked(self.library.is_favorite(track.path))
        self.setWindowTitle(f"{track.title} · {track.artist} — {APP_TITLE}")
        if self._tray is not None:
            self._tray.setToolTip(f"{track.title} · {track.artist}\n{APP_TITLE}")

    def _load_extras(self, track: Track) -> tuple[bytes | None, object]:
        """一次打开文件，同时取封面和内嵌歌词，并按 mtime/size 缓存。

        以前切一首歌要把同一个文件用 mutagen 打开 2~3 次（封面、内嵌歌词各一次）。
        """
        stamp = (track.mtime, track.size)
        cached = self._cover_cache.get(track.path)
        if cached is not None and cached[0] == stamp:
            return cached[1], cached[2]

        audio = open_audio(track.path)
        cover = read_cover_from(audio)
        lyrics = find_lyrics(track.path, audio=audio)
        if len(self._cover_cache) > 40:
            self._cover_cache.clear()
        self._cover_cache[track.path] = (stamp, cover, lyrics)
        return cover, lyrics

    @staticmethod
    def _lyrics_source_text(lyrics) -> str:
        if not lyrics or not lyrics.source:
            return ""
        if lyrics.source.lower().endswith(".lrc"):
            return "LRC"
        return lyrics.source

    def _on_position(self, position: int) -> None:
        if self._seeking:
            # 拖动中：时间与歌词跟随滑块（由 _on_slider_value 更新），
            # 别被播放器回传的位置覆盖。
            return
        self._syncing_slider = True
        self.slider.setValue(position)
        self._syncing_slider = False
        self.time_now.setText(fmt_time(position))
        self.lyrics.set_position(position)

    def _on_duration(self, duration: int) -> None:
        # setRange 引起的取值钳位不算用户操作，别触发 seek
        self._syncing_slider = True
        self.slider.setRange(0, max(1, duration))
        self._syncing_slider = False
        self.time_total.setText(fmt_time(duration))

    def _on_state(self, state) -> None:
        playing = self.player.is_playing
        self.btn_play.setIcon(make_icon("pause" if playing else "play", "#FFFFFF", 20))
        if self._tray is not None:
            self._tray_play.setIcon(make_icon("pause" if playing else "play", SUB, 14))
            self._tray_play.setText("暂停" if playing else "播放")

    def _begin_seek(self) -> None:
        self._seeking = True

    def _end_seek(self) -> None:
        self._seeking = False
        value = self.slider.value()
        self.player.seek(value)
        self.time_now.setText(fmt_time(value))
        self.lyrics.set_position(value)

    def _on_slider_value(self, value: int) -> None:
        if self._syncing_slider:
            return
        if self._seeking:
            self.time_now.setText(fmt_time(value))
            self.lyrics.set_position(value)
        else:
            self.player.seek(value)

    def _on_volume_changed(self, value: int) -> None:
        self.player.set_volume(value)
        self._muted = value == 0
        self._update_volume_icon()
        if value > 0:
            self._restore_volume = value
        self._volume_save_timer.start()

    def _save_volume(self) -> None:
        self.settings.setValue("audio/volume", self.volume_slider.value())

    def _update_volume_icon(self) -> None:
        name = "volume_mute" if (self._muted or self.volume_slider.value() == 0) else "volume"
        self.btn_mute.setIcon(make_icon(name, SUB, 18))
        self.btn_mute.setToolTip("取消静音" if self._muted else "静音")

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        if self._muted:
            if self.volume_slider.value() > 0:
                self._restore_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
        else:
            self.volume_slider.setValue(self._restore_volume or 72)
        self._update_volume_icon()

    def _show_equalizer(self) -> None:
        dialog = self.equalizer_dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_mode_changed(self, mode) -> None:
        icons = {
            PlayMode.SEQUENTIAL: "sequence",
            PlayMode.LOOP_ALL: "repeat",
            PlayMode.LOOP_ONE: "repeat_one",
            PlayMode.SHUFFLE: "shuffle",
        }
        color = SUB if mode == PlayMode.SEQUENTIAL else ACCENT
        self.btn_mode.setIcon(make_icon(icons.get(mode, "repeat"), color, 17))
        self.btn_mode.setToolTip(f"播放模式：{MODE_LABEL[mode]}（点击切换）")

    def _toggle_favorite_current(self) -> None:
        if self._current is None:
            self.btn_fav.setChecked(False)
            return
        state = self.library.toggle_favorite(self._current.path)
        self.btn_fav.setChecked(state)
        self.model.refresh_favorites()
        if self._view == self.VIEW_FAVORITES:
            self._reload_tracks(keep_state=True)
            self._update_header()
            self._sync_stack()

    def _toggle_lyrics_panel(self) -> None:
        visible = not self.lyrics_panel.isVisible()
        self.lyrics_panel.setVisible(visible)
        self.btn_lyrics.setChecked(visible)
        self.settings.setValue("ui/lyrics", visible)

    # ================================================================ 歌词偏移
    def _nudge_offset(self, delta: int) -> None:
        if not self.lyrics.has_synced:
            return
        self._set_offset(self.lyrics.delay + delta)

    def _set_offset(self, ms: int) -> None:
        ms = max(-20000, min(20000, int(ms)))
        self.lyrics.set_delay(ms)
        self._update_offset_label()
        if self._current is None:
            return
        path = self._current.path
        if ms:
            self._offsets[path] = ms
        else:
            self._offsets.pop(path, None)
        self._persist_offsets()

    def _persist_offsets(self) -> None:
        if len(self._offsets) > 400:
            for key in list(self._offsets)[: len(self._offsets) - 400]:
                self._offsets.pop(key, None)
        self.settings.setValue("lyrics/offsets", dict(self._offsets))

    def _update_offset_label(self) -> None:
        delay = self.lyrics.delay
        if delay == 0:
            text = "偏移 0.0s"
        else:
            sign = "+" if delay > 0 else "-"
            text = f"偏移 {sign}{abs(delay) / 1000:.1f}s"
        self.btn_offset_label.setText(text)
        synced = self.lyrics.has_synced
        for button in (self.btn_offset_minus, self.btn_offset_plus,
                       self.btn_offset_label):
            button.setEnabled(synced)
        self.btn_offset_label.setToolTip(
            "歌词偏移：正值表示歌词整体延后；点击归零"
            if synced else "当前歌曲没有逐行（LRC）歌词"
        )

    # ================================================================ 搜索
    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _on_search(self, text: str) -> None:
        self.proxy.set_query(text)
        self._update_header()
        self._sync_stack()

    # ================================================================ 右键菜单
    def _selected_paths(self) -> list[str]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        rows = sorted({index.row() for index in selection.selectedRows()})
        paths: list[str] = []
        for row in rows:
            source = self.proxy.mapToSource(self.proxy.index(row, 0))
            track = self.model.track_at(source.row())
            if track is not None:
                paths.append(track.path)
        return paths

    def _menu_paths_at(self, pos: QPoint) -> list[str]:
        """右键落点对应的曲目；点在未选中的行上时先把选中集切到那一行。"""
        index = self.table.indexAt(pos)
        if index.isValid():
            selection = self.table.selectionModel()
            if selection is not None and index.row() not in self.table.selected_rows():
                selection.select(
                    index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                self.table.setCurrentIndex(index)
        paths = self._selected_paths()
        if not paths and index.isValid():
            track = self.model.track_at(self.proxy.mapToSource(index).row())
            if track is not None:
                paths = [track.path]
        return paths

    def _show_table_menu(self, pos: QPoint) -> None:
        paths = self._menu_paths_at(pos)
        if not paths:
            return

        menu = QMenu(self)
        actions: dict[object, object] = {}

        play_action = menu.addAction(
            make_icon("play", SUB, 14), "播放" if len(paths) == 1 else f"播放选中 {len(paths)} 首"
        )
        actions[play_action] = lambda: self._play_paths(paths)

        menu.addSeparator()
        all_favorite = all(self.library.is_favorite(p) for p in paths)
        fav_action = menu.addAction(
            make_icon("heart", SUB, 14),
            "取消喜欢" if all_favorite else "添加到我喜欢的音乐",
        )
        actions[fav_action] = lambda: self._set_favorites(paths, not all_favorite)

        add_menu = menu.addMenu(make_icon("plus", SUB, 14), "添加到播放列表")
        for playlist in self.library.playlists:
            action = add_menu.addAction(playlist.name)
            actions[action] = (lambda pid=playlist.id: self._add_to_playlist(pid, paths))
        if self.library.playlists:
            add_menu.addSeparator()
        new_action = add_menu.addAction("新建播放列表…")
        actions[new_action] = lambda: self._create_playlist(paths)

        if self._view == self.VIEW_PLAYLIST:
            remove_action = menu.addAction(make_icon("trash", SUB, 14), "从当前列表移除")
            actions[remove_action] = lambda: self._remove_from_playlist(paths)

        menu.addSeparator()
        reveal_action = menu.addAction(make_icon("folder", SUB, 14), "在文件夹中显示")
        actions[reveal_action] = lambda: self._reveal_in_explorer(paths[0])

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen in actions:
            actions[chosen]()

    def _play_paths(self, paths: list[str]) -> None:
        wanted = set(paths)
        queue = [t for t in self._visible_tracks() if t.path in wanted]
        if not queue:
            queue = [t for t in (self.library.get(p) for p in paths) if t is not None]
        if queue:
            self.player.play_queue(queue, 0)

    def _set_favorites(self, paths: list[str], state: bool) -> None:
        # 一次写完整个集合，而不是每首歌各写一遍 library.json
        self.library.set_favorites(paths, state)
        self.model.refresh_favorites()
        if self._current is not None:
            self.btn_fav.setChecked(self.library.is_favorite(self._current.path))
        if self._view == self.VIEW_FAVORITES:
            self._reload_tracks(keep_state=True)
            self._update_header()
            self._sync_stack()

    def _add_to_playlist(self, playlist_id: str, paths: list[str]) -> None:
        added = self.library.add_to_playlist(playlist_id, paths)
        playlist = self.library.playlist(playlist_id)
        name = playlist.name if playlist else "播放列表"
        self._flash(f"已添加 {added} 首到「{name}」" if added else "这些歌曲已经在列表里了")

    def _remove_from_playlist(self, paths: list[str]) -> None:
        removed = self.library.remove_from_playlist(self._playlist_id, paths)
        self._flash(f"已从列表移除 {removed} 首")

    def _reveal_in_explorer(self, path: str) -> None:
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as exc:
            self._flash(f"无法打开文件夹：{exc}")

    def _show_playlist_menu(self, pos: QPoint) -> None:
        item = self.playlist_list.itemAt(pos)
        menu = QMenu(self)
        actions: dict[object, object] = {}

        if item is not None:
            playlist_id = str(item.data(Qt.ItemDataRole.UserRole))
            play_action = menu.addAction(make_icon("play", SUB, 14), "播放")
            actions[play_action] = lambda: self._play_playlist(playlist_id)
            rename_action = menu.addAction("重命名")
            actions[rename_action] = lambda: self._rename_playlist(playlist_id)
            delete_action = menu.addAction(make_icon("trash", SUB, 14), "删除播放列表")
            actions[delete_action] = lambda: self._delete_playlist(playlist_id)
            menu.addSeparator()

        new_action = menu.addAction(make_icon("plus", SUB, 14), "新建播放列表")
        actions[new_action] = lambda: self._create_playlist()

        chosen = menu.exec(self.playlist_list.mapToGlobal(pos))
        if chosen in actions:
            actions[chosen]()

    def _play_playlist(self, playlist_id: str) -> None:
        tracks = self.library.playlist_tracks(playlist_id)
        if tracks:
            self.select_view(self.VIEW_PLAYLIST, playlist_id)
            self.player.play_queue(tracks, 0)
        else:
            self._flash("这个播放列表还是空的")

    def _create_playlist(self, tracks: list[str] | None = None) -> None:
        name, ok = QInputDialog.getText(
            self, "新建播放列表", "列表名称：", text="我的歌单"
        )
        if not ok or not name.strip():
            return
        playlist = self.library.create_playlist(name.strip(), tracks or [])
        self._refresh_playlist_widget()
        self.select_view(self.VIEW_PLAYLIST, playlist.id)
        if tracks:
            self._flash(f"已创建《{playlist.name}》，添加了 {len(tracks)} 首歌曲")

    def _save_search_playlist(self) -> None:
        """把当前搜索结果整批保存成播放列表，方便下次直接听。"""
        query = self.search.text().strip()
        tracks = self._visible_tracks()
        if not query or not tracks:
            self._flash("先搜索出要保存的歌曲")
            return
        name, ok = QInputDialog.getText(
            self, "保存搜索为播放列表", "列表名称：",
            text=f"搜索：{query[:20]}",
        )
        if not ok or not name.strip():
            return
        playlist = self.library.create_playlist(
            name.strip(), [track.path for track in tracks]
        )
        self._refresh_playlist_widget()
        self._flash(f"已保存到《{playlist.name}》，共 {len(tracks)} 首")

    def _rename_playlist(self, playlist_id: str) -> None:
        playlist = self.library.playlist(playlist_id)
        if playlist is None:
            return
        name, ok = QInputDialog.getText(
            self, "重命名播放列表", "新名称：", text=playlist.name
        )
        if ok and name.strip():
            self.library.rename_playlist(playlist_id, name.strip())
            self._refresh_playlist_widget()
            self._update_header()

    def _delete_playlist(self, playlist_id: str) -> None:
        playlist = self.library.playlist(playlist_id)
        if playlist is None:
            return
        answer = QMessageBox.question(
            self, "删除播放列表",
            f"确定删除「{playlist.name}」吗？\n（只删除列表，不会删除音乐文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.library.delete_playlist(playlist_id)
        self._refresh_playlist_widget()
        self.select_view(self.VIEW_ALL)

    # ================================================================ 音乐库
    def _default_folder(self) -> str:
        saved = self.settings.value("ui/last_folder", "")
        if saved and os.path.isdir(str(saved)):
            return str(saved)
        music = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.MusicLocation
        )
        return music or os.path.expanduser("~")

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择音乐文件夹", self._default_folder()
        )
        if not folder:
            return
        self.settings.setValue("ui/last_folder", folder)
        if self.library.add_folder(folder):
            self._flash("正在扫描音乐文件…")
            self.start_scan()
        else:
            self._flash("这个文件夹已经在音乐库中了")

    def _auto_scan(self) -> None:
        folders, extra = self.library.scan_sources()
        if folders or extra:
            self.start_scan(quiet=bool(self.library.tracks))

    def start_scan(self, quiet: bool = False) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._flash("正在扫描中，请稍候…")
            return
        folders, extra = self.library.scan_sources()
        if not folders and not extra:
            self._flash("还没有添加音乐文件夹")
            return
        worker = ScanWorker(folders, extra, self.library.known_snapshot(), self)
        worker.progress.connect(self._on_scan_progress)
        worker.finished_ok.connect(self._on_scan_done)
        worker.finished.connect(self._on_scan_finished)
        worker.finished.connect(worker.deleteLater)
        self._scan_worker = worker
        if not quiet:
            self.view_sub.setText("正在扫描音乐文件…")
        worker.start()

    def _on_scan_progress(self, done: int, total: int, name: str) -> None:
        if total:
            self.view_sub.setText(f"扫描中 {done}/{total} · {name}")

    def _on_scan_done(self, tracks: list) -> None:
        count = self.library.apply_scan(tracks)
        # 拖拽播放触发的后台补扫不要盖掉「正在播放…」的提示
        if not self._flash_timer.isActive():
            self._flash(f"音乐库已更新：{count} 首歌曲")

    def _on_scan_finished(self) -> None:
        self._scan_worker = None
        if self._rescan_pending:
            self._rescan_pending = False
            QTimer.singleShot(0, lambda: self.start_scan(quiet=True))

    def _flash(self, message: str) -> None:
        self.view_sub.setText(message)
        self._flash_timer.start(2800)

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        actions: dict[object, object] = {}

        rescan = menu.addAction(make_icon("repeat", SUB, 14), "重新扫描音乐库")
        actions[rescan] = lambda: self.start_scan()

        if self.library.folders:
            folder_menu = menu.addMenu(make_icon("folder", SUB, 14), "移除音乐文件夹")
            for folder in self.library.folders:
                label = folder if len(folder) <= 38 else "…" + folder[-36:]
                action = folder_menu.addAction(label)
                actions[action] = (lambda f=folder: self._remove_folder(f))

        menu.addSeparator()
        tray_action = menu.addAction("最小化到托盘")
        tray_action.setCheckable(True)
        tray_action.setChecked(self._tray_enabled)
        tray_action.setEnabled(self._tray is not None)
        tray_action.toggled.connect(self._set_tray_enabled)

        open_data = menu.addAction("打开数据目录")
        actions[open_data] = lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(data_dir()))
        )
        about = menu.addAction("关于 Lumen")
        actions[about] = self._show_about
        menu.addSeparator()
        quit_action = menu.addAction("退出 Lumen")
        actions[quit_action] = self._quit

        chosen = menu.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height())))
        if chosen in actions:
            actions[chosen]()

    def _remove_folder(self, folder: str) -> None:
        answer = QMessageBox.question(
            self, "移除文件夹",
            f"不再从下面这个位置读取音乐？\n{folder}\n\n（不会删除硬盘上的文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self.library.remove_folder(folder)
        if removed:
            self._flash(f"已移除该文件夹，{removed} 首歌曲移出音乐库")
        else:
            self._flash("已移除该文件夹")

    def _show_about(self) -> None:
        show_about(
            APP_TITLE, self,
            icon_path=ICON_ROOT_PNG if ICON_ROOT_PNG.exists() else ICON_PNG,
            version=VERSION,
        )

    def open_paths(self, paths: list[str]) -> None:
        """打开外部传入的文件/文件夹（命令行、文件关联），效果等同拖进窗口。"""
        files: list[str] = []
        folders: list[str] = []
        for path in paths:
            if os.path.isdir(path):
                folders.append(path)
                files.extend(self._folder_audio_files(path))
            elif os.path.isfile(path) and is_audio(path):
                files.append(path)

        seen: set[str] = set()
        unique: list[str] = []
        for path in files:
            key = os.path.normcase(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)

        if not unique:
            self._flash("没有找到可播放的音频文件")
            return

        new_source = False
        for folder in folders:
            new_source = self.library.add_folder(folder) or new_source
        if self.library.add_files(unique):
            new_source = True

        name = self._drop_playlist_name(folders, unique) if len(unique) > 1 else ""
        self._show_window()
        self._begin_drop(unique, name, new_source)

    # ================================================================ 拖拽
    @staticmethod
    def _folder_audio_files(folder: str) -> list[str]:
        """递归取出文件夹里的音频，按自然序排列（01、02…10）。"""
        found: list[str] = []
        for root, dirs, names in os.walk(folder):
            dirs[:] = sorted(
                (name for name in dirs if not name.startswith(".")), key=natural_key
            )
            for name in sorted(names, key=natural_key):
                if is_audio(name):
                    found.append(os.path.join(root, name))
        return found

    def _collect_drop_paths(self, urls) -> tuple[list[str], list[str]]:
        """把拖进来的 URL 拆成「音频文件列表」和「文件夹列表」，文件去重保序。"""
        files: list[str] = []
        folders: list[str] = []
        for url in urls:
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path):
                folders.append(path)
                files.extend(self._folder_audio_files(path))
            elif os.path.isfile(path) and is_audio(path):
                files.append(path)

        seen: set[str] = set()
        unique: list[str] = []
        for path in files:
            key = os.path.normcase(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique, folders

    @staticmethod
    def _has_drop_payload(mime) -> bool:
        if not mime.hasUrls():
            return False
        for url in mime.urls():
            path = url.toLocalFile()
            if path and (
                os.path.isdir(path) or (os.path.isfile(path) and is_audio(path))
            ):
                return True
        return False

    def _show_drop_hint(self, visible: bool) -> None:
        if visible:
            self._place_drop_hint()
            self.drop_hint.show()
            self.drop_hint.raise_()
        else:
            self.drop_hint.hide()

    def dragEnterEvent(self, event) -> None:
        if self._has_drop_payload(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_hint(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._has_drop_payload(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._show_drop_hint(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._show_drop_hint(False)
        files, folders = self._collect_drop_paths(event.mimeData().urls())
        if not files:
            event.ignore()
            self._flash("没有找到可播放的音频文件")
            return
        event.acceptProposedAction()

        # 顺手把拖进来的位置登记到音乐库，下次启动仍在
        new_source = False
        for folder in folders:
            new_source = self.library.add_folder(folder) or new_source
        if self.library.add_files(files):
            new_source = True

        name = ""
        if len(files) > 1:
            name = self._drop_playlist_name(folders, files)
        self._begin_drop(files, name, new_source)

    def _drop_playlist_name(self, folders: list[str], files: list[str]) -> str:
        """给这次拖入的歌曲起个播放列表名字。"""
        if len(folders) == 1:
            return os.path.basename(os.path.normpath(folders[0])) or "拖入的音乐"
        parents = {os.path.dirname(path) for path in files}
        if len(parents) == 1:
            return os.path.basename(parents.pop()) or "拖入的音乐"
        return "拖入的音乐"

    def _begin_drop(self, files: list[str], name: str, need_scan: bool) -> None:
        known = self.library.known_snapshot()
        if len(files) <= self.DROP_SYNC_LIMIT:
            self._finish_drop(load_tracks(files, known), name, need_scan)
            return
        self._flash(f"正在准备 {len(files)} 首歌曲…")
        loader = TrackLoader(files, known, self)
        loader.progress.connect(self._on_drop_progress)
        loader.finished_ok.connect(
            lambda tracks: self._finish_drop(tracks, name, need_scan)
        )
        loader.finished.connect(self._on_drop_loader_finished)
        loader.finished.connect(loader.deleteLater)
        self._drop_loader = loader
        loader.start()

    def _on_drop_progress(self, done: int, total: int) -> None:
        if total:
            self.view_sub.setText(f"正在准备 {done}/{total} 首歌曲…")

    def _on_drop_loader_finished(self) -> None:
        self._drop_loader = None

    def _finish_drop(self, tracks: list, name: str = "", need_scan: bool = False) -> None:
        tracks = [track for track in (tracks or []) if track is not None]
        if not tracks:
            self._flash("这些文件读不出音频信息，无法播放")
            return

        self.library.merge_tracks(tracks)
        if name:
            playlist, created = self._ensure_drop_playlist(
                name, [track.path for track in tracks]
            )
            if self.search.text().strip():
                self.search.clear()
            self._refresh_playlist_widget()
            self.select_view(self.VIEW_PLAYLIST, playlist.id)
            prefix = "正在播放 · 已建立" if created else "正在播放 · 沿用"
            self._flash(f"{prefix}播放列表「{playlist.name}」（{len(tracks)} 首）")
        else:
            self._flash(f"正在播放：{tracks[0].title}")

        self.player.play_queue(tracks, 0)

        if need_scan:
            if self._scan_worker is None:
                self.start_scan(quiet=True)
            else:
                # 正在扫描：等这一轮结束后补一次，确保新拖入的文件夹也进库
                self._rescan_pending = True

    def _ensure_drop_playlist(self, name: str, paths: list[str]):
        """同名同曲的播放列表直接复用，否则用不重复的名字新建。"""
        for playlist in self.library.playlists:
            if playlist.name == name and playlist.tracks == paths:
                return playlist, False
        names = {playlist.name for playlist in self.library.playlists}
        unique = name
        index = 2
        while unique in names:
            unique = f"{name} ({index})"
            index += 1
        return self.library.create_playlist(unique, paths), True

    # ================================================================ 快捷键
    def keyPressEvent(self, event) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            if event.key() == Qt.Key.Key_Escape:
                focus.clear()
                self.table.setFocus()
                return
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)

        # 键盘上的媒体键（有焦点时也能用；全局监听见 MediaKeyWatcher）
        if key in (
            Qt.Key.Key_MediaTogglePlayPause,
            Qt.Key.Key_MediaPlay,
            Qt.Key.Key_MediaPause,
        ):
            self.player.toggle()
            event.accept()
            return
        if key == Qt.Key.Key_MediaNext:
            self.player.next(manual=True)
            event.accept()
            return
        if key == Qt.Key.Key_MediaPrevious:
            self.player.previous()
            event.accept()
            return
        if key == Qt.Key.Key_MediaStop:
            self._stop_playback()
            event.accept()
            return

        if key == Qt.Key.Key_Space:
            self.player.toggle()
            event.accept()
            return
        if key == Qt.Key.Key_Right and ctrl:
            self.player.seek_by(5000)
            return
        if key == Qt.Key.Key_Left and ctrl:
            self.player.seek_by(-5000)
            return
        if key == Qt.Key.Key_Right and alt:
            self.player.next(manual=True)
            return
        if key == Qt.Key.Key_Left and alt:
            self.player.previous()
            return
        if key == Qt.Key.Key_Delete and self._view == self.VIEW_PLAYLIST:
            paths = self._selected_paths()
            if paths:
                self._remove_from_playlist(paths)
            return
        if key == Qt.Key.Key_O and ctrl:
            self._choose_folder()
            return
        if key == Qt.Key.Key_F and ctrl:
            self._focus_search()
            return
        super().keyPressEvent(event)
