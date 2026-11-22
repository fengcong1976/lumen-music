"""新功能测试：托盘最小化、全局媒体键、拖动调整顺序、歌词偏移微调。

用法：venv/Scripts/python.exe tools/features_test.py
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (  # noqa: E402
    QBuffer,
    QCoreApplication,
    QEvent,
    QEventLoop,
    QIODevice,
    QItemSelectionModel,
    QMimeData,
    QPoint,
    QPointF,
    QSettings,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QIcon,
    QImage,
    QMouseEvent,
    QWheelEvent,
)
from PySide6.QtMultimedia import QMediaDevices  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QSystemTrayIcon,
    QTableView,
)

import ui.widgets as widgets_mod  # noqa: E402
import ui.main_window as main_window_module  # noqa: E402
from core.library import LAYOUT_VERSION, Library, ScanWorker  # noqa: E402
from core.lyrics import LyricLine, Lyrics, _lrc_candidates, _plain, parse_lrc  # noqa: E402
from core.media_keys import (  # noqa: E402
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
)
from core.metadata import Track, read_track  # noqa: E402
from core.player import PlayMode, Player  # noqa: E402
from core.single_instance import SingleInstance  # noqa: E402
from ui.lyrics_view import LyricsView  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.models import SongModel, TrackFilterProxy  # noqa: E402
from ui.theme import QSS, apply_font  # noqa: E402
from ui.widgets import ROWS_MIME, SongTable  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    RESULTS.append((bool(condition), label))
    print(("PASS  " if condition else "FAIL  ") + label)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def isolate_settings(base: Path) -> None:
    """把主窗口的 QSettings 重定向到临时 INI，避免测试改动真实配置。"""
    folder = base / "settings"
    folder.mkdir(parents=True, exist_ok=True)

    def factory(*args: object, **kwargs: object) -> QSettings:
        return QSettings(str(folder / "Lumen.ini"), QSettings.Format.IniFormat)

    # 主窗口用显式 INI 构造（QSettings.Format / Scope），补上被替换类名的属性引用
    factory.Format = QSettings.Format  # type: ignore[attr-defined]
    factory.Scope = QSettings.Scope  # type: ignore[attr-defined]
    main_window_module.QSettings = factory


def make_wav(path: Path, freq: float, seconds: float = 8.0, rate: int = 22050) -> None:
    total = int(seconds * rate)
    buffer = bytearray()
    for index in range(total):
        sample = int(9000 * math.sin(2 * math.pi * freq * index / rate))
        buffer += struct.pack("<h", sample)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(buffer))


def press_media_key(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


LRC_TEXT = """[ti:夜色电台]
[00:00.00]第一句
[00:02.00]第二句
[00:03.50]第三句
[00:05.00]第四句
[00:06.50]第五句
"""


def build_fixtures(base: Path) -> Path:
    music = base / "库"
    music.mkdir(parents=True, exist_ok=True)
    songs = [
        ("A - 一号.wav", 440.0, True),
        ("B - 二号.wav", 494.0, False),
        ("C - 三号.wav", 523.0, False),
        ("D - 四号.wav", 587.0, False),
    ]
    for name, freq, with_lyrics in songs:
        path = music / name
        make_wav(path, freq)
        if with_lyrics:
            path.with_suffix(".lrc").write_text(LRC_TEXT, encoding="utf-8")
    return music


def main() -> int:
    QCoreApplication.setOrganizationName("LumenAudio")
    QCoreApplication.setApplicationName("LumenFeatures")
    app = QApplication(sys.argv)
    apply_font(app)
    app.setStyleSheet(QSS)

    base = Path(tempfile.mkdtemp(prefix="lumen_features_"))
    isolate_settings(base)
    music = build_fixtures(base)

    library = Library()
    library.file = base / "library.json"
    library.folders = []
    library.extra_files = []
    library.tracks = {}
    library.favorites = set()
    library.playlists = []
    library.add_folder(str(music))
    scanned: list = []
    worker = ScanWorker(library.folders, [], {}, None)
    worker.finished_ok.connect(lambda tracks: scanned.extend(tracks))
    worker.run()
    library.apply_scan(scanned)

    player = Player()
    player.set_volume(5)

    # 默认播放设备：启动即跟随系统缺省设备，没变化时不会重复切换
    default_output = QMediaDevices.defaultAudioOutput()
    check(
        not default_output.isNull()
        and player._output_id == bytes(default_output.id()),
        "启动时使用系统缺省播放设备",
    )
    output_before = player._output_id
    player._follow_default_output()
    check(player._output_id is output_before, "默认设备未变时不重复切换输出")
    player.set_volume(5)
    check(player.volume() == 5, f"音量设置生效: {player.volume()}")

    # 均衡器：10 段 + VLC 预设可用
    check(player.eq_band_count() == 10, f"均衡器频段数: {player.eq_band_count()}")
    check(player.eq_preset_count() >= 10, f"均衡器预设数: {player.eq_preset_count()}")
    check(player.apply_eq_preset(0), "应用均衡器预设")
    check(player.apply_eq_custom([1.5] * 10), "应用自定义均衡器增益")
    player.disable_eq()
    window = MainWindow(library, player)
    window.resize(1280, 820)
    window.show()
    wait(500)

    paths = {read_track(str(p)).title: str(p) for p in music.glob("*.wav")}
    lyric_path = paths["一号"]

    # ================================================ 1. 歌词偏移
    row = next(
        r for r in range(window.proxy.rowCount())
        if window._track_at_proxy_row(r) and window._track_at_proxy_row(r).path == lyric_path
    )
    window._on_row_activated(window.proxy.index(row, 0))
    wait(600)
    player.pause()          # 暂停后位置固定，偏移断言才稳定
    wait(200)
    player.seek(2000)
    wait(300)
    check(window.lyrics._synced, "歌词已同步")
    check(window.lyrics._current == 1, f"2 秒处高亮第二句: {window.lyrics._current}")

    window.btn_offset_plus.click()
    wait(150)
    check(window.lyrics.delay == 500, f"+0.5s 后偏移量: {window.lyrics.delay}")
    check(
        window.lyrics._current == 0,
        f"延后 0.5s 后退回第一句: {window.lyrics._current}",
    )
    check(
        window.btn_offset_label.text() == "偏移 +0.5s",
        f"偏移标签: {window.btn_offset_label.text()}",
    )

    window.btn_offset_plus.click()
    window.btn_offset_plus.click()
    wait(150)
    check(window.lyrics.delay == 1500, f"连续点击累计: {window.lyrics.delay}")
    check(
        window._offsets.get(lyric_path) == 1500,
        "偏移按歌曲记忆",
    )
    check(
        window.settings.value("lyrics/offsets", {}).get(lyric_path) == 1500,
        "偏移已写入设置",
    )
    window.grab().save(str(ROOT / "docs" / "preview_offset.png"))

    window.btn_offset_label.click()      # 点击中间的标签归零
    wait(150)
    check(window.lyrics.delay == 0, "点击标签归零")
    check(lyric_path not in window._offsets, "归零后清除记忆")

    window.btn_offset_minus.click()
    wait(150)
    check(window.lyrics.delay == -500, f"-0.5s 后偏移量: {window.lyrics.delay}")
    check(
        window.lyrics._current == 1,
        f"提前 0.5s 时 2 秒处仍是第二句: {window.lyrics._current}",
    )
    window.btn_offset_label.click()
    wait(150)

    # 无歌词的歌曲：按钮应禁用
    other_row = next(
        r for r in range(window.proxy.rowCount())
        if window._track_at_proxy_row(r) and window._track_at_proxy_row(r).path in (
            paths["二号"], paths["三号"], paths["四号"]
        )
    )
    window._on_row_activated(window.proxy.index(other_row, 0))
    wait(400)
    check(not window.btn_offset_plus.isEnabled(), "无歌词时偏移按钮禁用")

    # ================================================ 2. 拖动排序
    window.select_view(window.VIEW_ALL)
    wait(200)
    before = [t.title for t in window._visible_tracks()]
    total = len(before)
    check(total == 4, f"列表 {total} 首")

    window._on_rows_dropped([total - 1], 0)
    wait(200)
    after = [t.title for t in window._visible_tracks()]
    check(after[0] == before[-1], f"拖到最前生效: {after[0]} == {before[-1]}")
    check(sorted(after) == sorted(before), "拖动不丢歌")

    # 拖动后播放队列跟随新顺序
    window._play_all()
    wait(400)
    window._on_rows_dropped([0], total)
    wait(200)
    tail = [t.title for t in window._visible_tracks()]
    check(
        [t.title for t in player.queue] == tail,
        "播放队列跟随拖动后的顺序",
    )
    check(player.queue[player.index].path == player.current_track.path, "当前曲目索引正确")

    # 多选一起拖
    window.table.selectRow(0)
    window.table.selectionModel().select(
        window.proxy.index(1, 0),
        window.table.selectionModel().SelectionFlag.Select
        | window.table.selectionModel().SelectionFlag.Rows,
    )
    wait(100)
    picked = [t.title for t in window._visible_tracks()[:2]]
    window._on_rows_dropped([0, 1], total)
    wait(200)
    moved = [t.title for t in window._visible_tracks()]
    check(moved[-2:] == picked, f"多选一起移动: {moved[-2:]}")

    # 切走视图再回来，拖动过的顺序仍然保留
    window.select_view(window.VIEW_RECENT)
    wait(150)
    window.select_view(window.VIEW_ALL)
    wait(150)
    kept = [t.title for t in window._visible_tracks()]
    check(kept == moved, f"切换视图后顺序保留: {kept}")

    # 排序列排序后会退回自定义顺序
    window.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    wait(150)
    check(window.table.horizontalHeader().sortIndicatorSection() >= 0, "已按标题排序")
    window._on_rows_dropped([total - 1], 0)
    wait(150)
    check(
        window.table.horizontalHeader().sortIndicatorSection() == -1,
        "拖动后取消列排序",
    )

    # 播放列表里的顺序会保存
    window.select_view(window.VIEW_PLAYLIST)
    playlist = library.create_playlist(
        "拖动测试", [t.path for t in library.all_tracks()]
    )
    window.select_view(window.VIEW_PLAYLIST, playlist.id)
    wait(200)
    order0 = [t.title for t in window._visible_tracks()]
    window._on_rows_dropped([0], len(order0))
    wait(200)
    saved = [library.get(p).title for p in library.playlist(playlist.id).tracks]
    check(saved == order0[1:] + [order0[0]], f"播放列表顺序已保存: {saved}")
    on_disk = json.loads((base / "library.json").read_text(encoding="utf-8"))
    disk_order = [
        Path(p).stem.split(" - ")[-1]
        for p in next(pl for pl in on_disk["playlists"] if pl["id"] == playlist.id)["tracks"]
    ]
    check(disk_order == order0[1:] + [order0[0]], "顺序已写进 library.json")

    # 落点计算与拖动预览
    table = window.table
    rect0 = table.visualRect(window.proxy.index(0, 0))
    check(table._insert_row_at(QPoint(20, rect0.top() + 2)) == 0, "落点上沿 = 插到第 0 行")
    check(table._insert_row_at(QPoint(20, rect0.bottom() - 2)) == 1, "落点下沿 = 插到第 1 行")
    check(
        table._insert_row_at(QPoint(20, table.viewport().height() + 60))
        == window.proxy.rowCount(),
        "空白处落点 = 列表末尾",
    )
    table._drop_row = 2
    pixmap = table.viewport().grab()
    check(not pixmap.isNull(), "拖动指示线绘制正常")
    window.grab().save(str(ROOT / "docs" / "preview_drag.png"))
    table._clear_indicator()
    check(not SongTable._drag_pixmap(3).isNull(), "拖动预览图生成正常")

    # ---- 真实拖放事件路径 ----
    rows_mime = QMimeData()
    rows_mime.setData(ROWS_MIME, b"0")
    enter = QDragEnterEvent(
        QPoint(20, 40),
        Qt.DropAction.MoveAction,
        rows_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    table.dragEnterEvent(enter)
    check(enter.isAccepted(), "行拖动事件被表格接受")

    url_mime = QMimeData()
    url_mime.setUrls([QUrl.fromLocalFile(lyric_path)])
    url_enter = QDragEnterEvent(
        QPoint(20, 40),
        Qt.DropAction.CopyAction,
        url_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    table.dragEnterEvent(url_enter)
    check(not url_enter.isAccepted(), "外部文件拖入不拦截（交给主窗口）")

    dropped: list[tuple[list[int], int]] = []
    table.rowsDropped.connect(lambda rows, row: dropped.append((rows, row)))
    order_before = [t.title for t in window._visible_tracks()]
    drop = QDropEvent(
        QPointF(
            20,
            table.visualRect(
                window.proxy.index(window.proxy.rowCount() - 1, 0)
            ).bottom() - 2,
        ),
        Qt.DropAction.MoveAction,
        rows_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    table.dropEvent(drop)
    wait(150)
    check(len(dropped) == 1, f"dropEvent 发出顺序调整信号: {dropped}")
    order_after = [t.title for t in window._visible_tracks()]
    check(
        order_after == order_before[1:] + order_before[0:1],
        f"真实落点生效: {order_after}",
    )

    # ---- 鼠标按下并拖动会启动 QDrag ----
    class _FakeDrag:
        started: list = []

        def __init__(self, source):
            self.source = source
            self.mime = None

        def setMimeData(self, mime):
            self.mime = mime

        def setPixmap(self, pixmap):
            pass

        def setHotSpot(self, point):
            pass

        def exec(self, *args):
            type(self).started.append(self.mime)
            return Qt.DropAction.MoveAction

    original_drag = widgets_mod.QDrag
    widgets_mod.QDrag = _FakeDrag
    try:
        viewport = table.viewport()
        start = QPoint(24, table.visualRect(window.proxy.index(0, 0)).center().y())
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(start + QPoint(0, 24)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(viewport, move)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        check(len(_FakeDrag.started) == 1, "按住并移动鼠标会启动拖动")
        started_mime = _FakeDrag.started[0] if _FakeDrag.started else None
        check(
            bool(started_mime) and started_mime.hasFormat(ROWS_MIME),
            "拖动携带行号数据",
        )
    finally:
        widgets_mod.QDrag = original_drag

    # ================================================ 3. 托盘 + 媒体键
    if QSystemTrayIcon.isSystemTrayAvailable():
        check(window._tray is not None, "托盘图标已创建")
        check(window._tray.isVisible(), "托盘图标可见")
        window._tray_enabled = True

        window.showMinimized()
        wait(500)
        check(not window.isVisible(), "最小化后缩到托盘")
        window._show_window()
        wait(300)
        check(window.isVisible() and not window.isMinimized(), "从托盘恢复窗口（最小化）")

        window.close()          # 应缩到托盘而不是退出
        wait(300)
        check(not window.isVisible(), "关闭窗口后隐藏到托盘")
        check(player.is_playing or player.current_track is not None, "托盘状态下播放未中断")
        window._show_window()
        wait(300)
        check(window.isVisible(), "从托盘恢复窗口")
        check(window._tray_menu.actions(), "托盘菜单已构建")
    else:
        check(True, "当前环境没有系统托盘，跳过托盘检查")

    check(window._media_keys.enabled, f"全局媒体键已启用（{window._media_keys.method}）")
    window._show_window()
    window._play_all()
    wait(600)
    playing = player.is_playing
    press_media_key(VK_MEDIA_PLAY_PAUSE)
    wait(500)
    check(player.is_playing != playing, "媒体键：播放/暂停切换")
    press_media_key(VK_MEDIA_PLAY_PAUSE)
    wait(500)

    current = player.current_track.path
    press_media_key(VK_MEDIA_NEXT_TRACK)
    wait(500)
    check(player.current_track.path != current, "媒体键：下一首")
    current = player.current_track.path
    press_media_key(VK_MEDIA_PREV_TRACK)
    wait(500)
    check(player.current_track.path != current, "媒体键：上一首")

    # 窗口有焦点时的媒体键（Qt 事件路径）
    window.activateWindow()
    before_path = player.current_track.path
    QTest.keyClick(window, Qt.Key.Key_MediaNext)
    wait(400)
    check(player.current_track.path != before_path, "窗口内媒体键同样生效")

    # ================================================ 4. 应用图标
    from ui.icons import app_icon, icon_file  # noqa: E402

    icon_path = icon_file()
    check(icon_path.exists(), f"图标文件存在：{icon_path.name}")
    ico = QIcon(str(icon_path))
    sizes = {(s.width(), s.height()) for s in ico.availableSizes()}
    check(not ico.isNull(), "ICO 可被 Qt 读取")
    check({16, 32, 48, 256}.issubset({w for w, _ in sizes}), f"ICO 含多档尺寸: {sorted(sizes)}")
    check(
        all(not ico.pixmap(s, s).isNull() for s in (16, 32, 48, 256)),
        "各尺寸都能渲染出位图",
    )
    check(not app_icon().isNull(), "app_icon() 返回有效图标")
    check(app_icon() is app_icon(), "app_icon() 结果已缓存")
    check(not window.windowIcon().isNull(), "窗口栏使用应用图标")

    if sys.platform == "win32":
        import main as app_main  # noqa: E402

        app_main._claim_taskbar_identity()
        pointer = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(
            ctypes.byref(pointer)
        )
        app_id = pointer.value if result == 0 and pointer.value else ""
        check(app_id.startswith("LumenAudio."), f"任务栏应用标识已设置: {app_id}")

    # ================================================ 5. 拖拽进来播放
    drop_dir = base / "拖入专辑"
    drop_dir.mkdir()
    for name in ("10 - 丙.wav", "02 - 乙.wav", "01 - 甲.wav"):
        make_wav(drop_dir / name, 440, seconds=6)
    ordered = [
        str(drop_dir / "01 - 甲.wav"),
        str(drop_dir / "02 - 乙.wav"),
        str(drop_dir / "10 - 丙.wav"),
    ]

    def urls_event(paths: list[str], kind):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        if kind == "enter":
            event = QDragEnterEvent(
                QPoint(300, 300), Qt.DropAction.CopyAction, mime,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            )
        else:
            event = QDropEvent(
                QPointF(300, 300), Qt.DropAction.CopyAction, mime,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            )
        QApplication.sendEvent(window, event)
        return event

    def drag_and_drop(paths: list[str]):
        """真实手势是 dragEnter → drop，Qt 要先收到 enter 才会派发 drop。"""
        enter = urls_event(paths, "enter")
        dropped = urls_event(paths, "drop")
        wait(80)
        return enter, dropped

    def wait_scan() -> None:
        for _ in range(4):
            worker = window._scan_worker
            if worker is None:
                break
            worker.wait(5000)
            wait(200)
        wait(120)

    enter = urls_event([str(drop_dir)], "enter")
    check(enter.isAccepted(), "拖入文件夹时接受拖放")
    check(window.drop_hint.isVisible(), "拖拽时显示「松开即播放」提示")
    QApplication.sendEvent(window, QDragLeaveEvent())
    check(not window.drop_hint.isVisible(), "拖拽离开后提示自动消失")

    before_playlists = len(library.playlists)
    drag_and_drop([str(drop_dir)])
    wait(800)
    check(
        player.current_track is not None
        and player.current_track.path == ordered[0],
        "放下文件夹后从第一首开始",
    )
    check([track.path for track in player.queue] == ordered, "播放队列按 01/02/10 自然排序")
    check(player.is_playing, "拖入后自动开始播放")
    check(not window.drop_hint.isVisible(), "放下后提示浮层隐藏")
    check(len(library.playlists) == before_playlists + 1, "多文件拖入自动建立播放列表")
    playlist = library.playlists[-1]
    check(playlist.name == "拖入专辑", f"播放列表名取自文件夹：{playlist.name}")
    check(playlist.tracks == ordered, "列表顺序与播放顺序一致")
    check(
        window._view == window.VIEW_PLAYLIST and window._playlist_id == playlist.id,
        "自动切到新建的播放列表",
    )
    check(all(path in library.tracks for path in ordered), "拖入的歌曲立即入库")
    wait_scan()

    drag_and_drop([str(drop_dir)])
    wait_scan()
    check(
        len(library.playlists) == before_playlists + 1,
        "同一文件夹再拖一次不会重复建列表",
    )

    loose = base / "零散单曲"
    loose.mkdir()
    for name in ("A.wav", "B.wav"):
        make_wav(loose / name, 560, seconds=6)
    before_playlists = len(library.playlists)
    drag_and_drop([str(loose / "A.wav"), str(loose / "B.wav")])
    wait_scan()
    check(len(library.playlists) == before_playlists + 1, "拖入多个文件也建立播放列表")
    check(
        library.playlists[-1].name == "零散单曲",
        f"列表名取自共同目录：{library.playlists[-1].name}",
    )

    before_playlists = len(library.playlists)
    drag_and_drop([str(loose / "A.wav")])
    wait(500)
    check(len(library.playlists) == before_playlists, "单个文件不建播放列表")
    check(
        player.current_track.path == str(loose / "A.wav"),
        "单个文件拖入直接播放",
    )

    note = base / "note.txt"
    note.write_text("not audio", encoding="utf-8")
    rejected_enter = urls_event([str(note)], "enter")
    check(not rejected_enter.isAccepted(), "非音频文件拖入时被拒绝")
    check(not window.drop_hint.isVisible(), "非音频文件不显示拖放提示")

    # 超过阈值（40 首）时改走后台线程，避免界面卡住
    bulk = base / "批量专辑"
    bulk.mkdir()
    for index in range(1, 43):
        make_wav(bulk / f"{index:02d}.wav", 400 + index, seconds=1)
    before_playlists = len(library.playlists)
    urls_event([str(bulk)], "enter")
    urls_event([str(bulk)], "drop")          # dropEvent 同步执行，返回时线程已启动
    check(window._drop_loader is not None, "超过 40 首时改用后台线程读取标签")
    for _ in range(50):
        if window._drop_loader is None:
            break
        wait(100)
    wait(500)
    check(len(player.queue) == 42, f"大批量拖入全部进入播放队列：{len(player.queue)}")
    check(len(library.playlists) == before_playlists + 1, "大批量拖入同样建立播放列表")
    check(player.queue[0].path.endswith("01.wav"), "大批量按编号顺序起播")
    wait_scan()

    # ================================================ 6. 回归用例（本轮修复）
    # 6.1 双击托盘图标：Windows 先发 Trigger 再发 DoubleClick，窗口应保持可见
    if window._tray is not None:
        window._hide_to_tray()
        wait(250)
        check(not window.isVisible(), "回归：窗口已缩到托盘")
        window._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        window._on_tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        wait(300)
        check(
            window.isVisible() and not window.isMinimized(),
            "回归：双击托盘图标恢复窗口（不再被藏起来）",
        )

    # 6.2 切歌时歌词不沿用上一首的播放位置
    probe_view = LyricsView()
    probe_view.resize(320, 420)
    fixture = parse_lrc("[00:02.00]一\n[00:12.00]二\n")
    probe_view.set_lyrics(fixture)
    probe_view.set_position(19000)
    check(probe_view._current == 1, f"回归：旧曲 19 秒在第 2 句（{probe_view._current}）")
    probe_view.set_lyrics(fixture)
    check(
        probe_view._current == -1,
        f"回归：换歌后不沿用旧位置（{probe_view._current}）",
    )
    probe_view.deleteLater()

    # 6.3 拖动进度条时，时间与歌词不被播放器回传位置覆盖
    window.time_now.setText("1:11")
    window._seeking = True
    window._on_position(999999)
    check(window.time_now.text() == "1:11", "回归：拖动中时间标签不被覆盖")
    window._seeking = False
    window._on_position(player.position())

    # 6.4 右键未选中的行 → 先选中它，菜单不再作用于旧选区
    window.select_view(window.VIEW_ALL)
    wait(200)
    window.table.selectRow(0)
    wait(100)
    target_row = min(2, window.proxy.rowCount() - 1)
    target_track = window._track_at_proxy_row(target_row)
    hit = window.table.visualRect(window.proxy.index(target_row, 0)).center()
    picked_paths = window._menu_paths_at(hit)
    check(
        picked_paths == [target_track.path],
        f"回归：右键按落点选行（{len(picked_paths)} 首）",
    )

    # 6.5 被停止的扫描不得上报结果（否则会用不完整结果覆写曲库）
    stopped_result: list = []
    stop_worker = ScanWorker([str(music)], [], {})
    stop_worker.finished_ok.connect(lambda tracks: stopped_result.append(tracks))
    stop_worker.request_stop()
    stop_worker.run()
    check(not stopped_result, "回归：停止的扫描不再上报结果")

    # 6.6 扫描结果之外的现存曲目要留住；移除目录不误伤同名兄弟目录
    audit_lib = Library()
    audit_root = base / "audit"
    music_a = audit_root / "Music"
    music_b = audit_root / "Music2"
    music_a.mkdir(parents=True)
    music_b.mkdir(parents=True)
    make_wav(music_a / "a.wav", 300, seconds=2)
    make_wav(music_b / "b.wav", 320, seconds=2)
    audit_lib.file = audit_root / "library.json"
    audit_lib.folders = [str(music_a), str(music_b)]
    audit_lib.extra_files = []
    audit_lib.tracks = {}
    audit_lib.favorites = set()
    audit_lib.playlists = []
    track_a = read_track(str(music_a / "a.wav"))
    track_b = read_track(str(music_b / "b.wav"))
    audit_lib.merge_tracks([track_a, track_b])
    audit_lib.favorites = {track_a.path, track_b.path}
    audit_lib.create_playlist("合集", [track_a.path, track_b.path])

    audit_lib.apply_scan([track_a])     # 模拟「扫描时 b 刚拖进来，还没被扫到」
    check(track_b.path in audit_lib.tracks, "回归：扫描外的现存曲目不被丢弃")
    check(
        track_b.path in audit_lib.playlists[0].tracks,
        "回归：列表条目不被误删",
    )

    removed_count = audit_lib.remove_folder(str(music_a))
    check(removed_count == 1, f"回归：只移除本目录的 1 首（{removed_count}）")
    check(track_b.path in audit_lib.tracks, "回归：移除 Music 不影响 Music2")
    check(track_a.path not in audit_lib.favorites, "回归：被移除目录的收藏一并清理")
    check(
        audit_lib.folders == [str(music_b)],
        f"回归：目录列表只剩 Music2（{audit_lib.folders}）",
    )
    check(
        audit_lib.playlists[0].tracks == [track_b.path],
        "回归：播放列表里只剩 Music2 的歌",
    )

    window.select_view(window.VIEW_ALL)
    wait(200)

    # ================================================ 7. 回归用例（第二批：性能与边界）
    # 7.1 库内容变化不再整表 reset：选中行跟着歌走，而不是跟着行号走
    probe_model = SongModel(library)
    probe_table = QTableView()
    probe_table.setModel(probe_model)
    probe_table.resize(560, 320)
    probe_table.show()
    named = [
        Track(path=f"D:/probe/{name}.wav", title=name, artist="A", album="B", duration=10)
        for name in "ABCDE"
    ]
    probe_model.set_tracks(named)
    wait(120)
    probe_sel = probe_table.selectionModel()
    probe_sel.select(
        probe_model.index(2, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect
        | QItemSelectionModel.SelectionFlag.Rows,
    )

    probe_model.sync_tracks([named[0], named[3], named[2], named[1], named[4]])
    wait(80)
    probe_rows = [index.row() for index in probe_sel.selectedRows()]
    check(
        probe_rows == [2] and probe_model.track_at(2).title == "C",
        f"回归：换顺序后选中仍在本曲（{probe_rows}）",
    )

    probe_model.sync_tracks([named[3], named[2], named[1], named[4]])      # 删掉 A
    wait(80)
    probe_rows = [index.row() for index in probe_sel.selectedRows()]
    check(
        probe_rows and probe_model.track_at(probe_rows[0]).title == "C",
        f"回归：删除一行后选中仍在本曲（{probe_rows}）",
    )

    probe_model.sync_tracks([named[3], named[0], named[2], named[1], named[4]])
    wait(80)
    probe_rows = [index.row() for index in probe_sel.selectedRows()]
    check(
        probe_rows and probe_model.track_at(probe_rows[0]).title == "C",
        f"回归：插入一行后选中仍在本曲（{probe_rows}）",
    )
    probe_table.deleteLater()

    # 7.2 批量收藏只写一次 library.json（以前每首歌各写一遍整份文件）
    write_calls: list[int] = []
    real_save = library.save
    library.save = lambda: write_calls.append(1)      # type: ignore[assignment]
    batch_paths = [t.path for t in library.all_tracks()[:3]]
    library.set_favorites(batch_paths, True)
    library.set_favorites(batch_paths, True)          # 已经是收藏，不该再写
    library.save = real_save                          # type: ignore[assignment]
    check(
        len(write_calls) == 1 and all(library.is_favorite(p) for p in batch_paths),
        f"回归：批量收藏只写一次盘（{len(write_calls)} 次）",
    )
    library.set_favorites(batch_paths, False)

    # 7.3 顺序播放播完后按播放键：从头再来，而不是重播最后一首
    batch_tracks = library.all_tracks()[:3]
    player.mode = PlayMode.SEQUENTIAL
    player.play_queue(batch_tracks, 0)
    player.play_index(len(batch_tracks) - 1)
    wait(150)
    player._player.stop()
    player._finished = True
    player.toggle()
    wait(200)
    check(player.index == 0, f"回归：播完按播放从第一首开始（{player.index}）")

    # 7.4 首曲按上一首：回到开头并重新起播（以前停在原位不动）
    player.play_queue([batch_tracks[0]], 0)
    wait(400)
    player.mode = PlayMode.SEQUENTIAL
    player._player.stop()
    wait(100)
    player.previous()
    wait(400)
    check(
        player.index == 0 and player.is_playing,
        f"回归：首曲上一首回到开头并继续播放（{player.index}/{player.is_playing}）",
    )

    # 7.5 同名 lrc 直取，不再每次切歌遍历整个目录
    candidates = _lrc_candidates(lyric_path)
    check(
        len(candidates) == 1 and candidates[0].suffix.lower() == ".lrc",
        f"回归：同名 lrc 快路径命中（{len(candidates)} 个）",
    )
    check(
        not _lrc_candidates(paths["二号"]),
        "回归：没有同名 lrc 时不会误取同目录其它歌词",
    )

    # 7.6 单实例：第二次启动只唤起已有窗口，并把文件转交给它
    first_instance = SingleInstance("LumenFeatures.Probe")
    second_instance = SingleInstance("LumenFeatures.Probe")
    activations: list[int] = []
    forwarded: list[list] = []
    first_instance.activated.connect(lambda: activations.append(1))
    first_instance.open_requested.connect(lambda ps: forwarded.append(list(ps)))
    first_ok = first_instance.acquire()
    second_ok = second_instance.acquire([r"C:\演示\01. 歌曲.mp3"])
    wait(300)
    check(first_ok and not second_ok, "回归：第二次启动不会开出第二个播放器")
    check(bool(activations), f"回归：已有实例收到唤起（{len(activations)} 次）")
    check(
        bool(forwarded) and forwarded[-1] == [r"C:\演示\01. 歌曲.mp3"],
        f"回归：文件关联路径转交已有实例（{forwarded}）",
    )
    first_instance.release()
    second_instance.release()

    # 7.7 封面按控件尺寸解码，不整张大图解码后再缩
    cover_image = QImage(900, 900, QImage.Format.Format_RGB32)
    cover_image.fill(QColor("#2E38C6"))
    cover_buffer = QBuffer()
    cover_buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    cover_image.save(cover_buffer, "PNG")
    cover_bytes = bytes(cover_buffer.data())
    cover_buffer.close()
    from ui.widgets import _cover_pixmap  # noqa: E402

    scaled = _cover_pixmap(cover_bytes, 58, 58, 1.0)
    check(
        scaled is not None and scaled.width() == 58 and scaled.height() == 58,
        f"回归：封面按控件尺寸解码（{scaled.width() if scaled else 0}px）",
    )
    check(_cover_pixmap(None, 58, 58, 1.0) is None, "回归：没有封面时返回空位图")

    # 7.8 搜索也能按文件名命中（标签里没有这个词）
    name_model = SongModel(library)
    name_model.set_tracks([
        Track(path="D:/probe/夜曲 demo.wav", title="无关标题", artist="某人",
              album="某专辑", duration=10),
    ])
    name_proxy = TrackFilterProxy()
    name_proxy.setSourceModel(name_model)
    name_proxy.set_query("夜曲demo")
    check(name_proxy.rowCount() == 0, "回归：文件名中间有空格时不误命中")
    name_proxy.set_query("夜曲")
    check(name_proxy.rowCount() == 1, "回归：搜索能按文件名命中")

    # 7.8.1 搜索结果可整批存成播放列表
    window.select_view(window.VIEW_ALL)
    window.search.setText("号")
    wait(150)
    check(window.proxy.rowCount() == 4, f"回归：搜索出 {window.proxy.rowCount()} 首")
    check(window.btn_save_search.isVisibleTo(window), "回归：搜索有结果时出现「存为歌单」")

    class _FakeInput:
        @staticmethod
        def getText(*args, **kwargs):
            return "搜索歌单", True

    original_input = main_window_module.QInputDialog
    main_window_module.QInputDialog = _FakeInput
    try:
        before_playlists = len(library.playlists)
        window.btn_save_search.click()
        wait(150)
        saved = library.playlists[-1] if library.playlists else None
        check(
            saved is not None and saved.name == "搜索歌单"
            and len(library.playlists) == before_playlists + 1,
            f"回归：搜索结果存为歌单（{saved.name if saved else '无'}）",
        )
        check(
            saved is not None and len(library.playlist_tracks(saved.id)) == 4,
            "回归：歌单包含全部搜索结果",
        )
    finally:
        main_window_module.QInputDialog = original_input

    window.search.clear()
    wait(150)
    check(not window.btn_save_search.isVisibleTo(window), "回归：清空搜索后按钮隐藏")

    # 7.9 手动滚动歌词后停手自动回中；纯文本歌词可滚动
    scroll_view = LyricsView()
    scroll_view.resize(360, 400)
    scroll_view.show()
    scroll_view.set_lyrics(parse_lrc("".join(f"[00:{i:02d}.00]第{i}句\n" for i in range(30))))
    scroll_view.set_position(12000)
    wait(200)
    anchor = scroll_view._offset
    scroll_view.wheelEvent(
        QWheelEvent(
            QPointF(180, 200), QPointF(180, 200), QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
    )
    wait(60)
    check(
        abs(scroll_view._offset - anchor) > 1 and not scroll_view.following,
        f"回归：滚轮能手动浏览歌词（{round(scroll_view._offset - anchor, 1)}）",
    )
    scroll_view._resume_following()
    wait(400)
    check(
        scroll_view.following and abs(scroll_view._offset - anchor) < 2,
        f"回归：停手后自动回到当前句（{round(scroll_view._offset, 1)}）",
    )
    plain_view = LyricsView()
    plain_view.resize(300, 120)
    plain_view.set_lyrics(_plain("第一行\n第二行\n第三行\n第四行\n第五行\n\n第六行", "测试"))
    plain_view.show()
    wait(100)
    plain_view.wheelEvent(
        QWheelEvent(
            QPointF(150, 60), QPointF(150, 60), QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
    )
    check(plain_view._offset < 0, f"回归：纯文本歌词可滚动（{round(plain_view._offset, 1)}）")
    plain_view.deleteLater()
    scroll_view.deleteLater()

    # 7.9.1 超长歌词自动折行，不再被省略号截断
    long_text = "这是一句特别长的歌词用来验证自动换行是否完整显示" * 3
    wrap_view = LyricsView()
    wrap_view.resize(360, 400)
    wrap_view.show()
    wrap_view.set_lyrics(Lyrics(lines=[LyricLine(time=0, text=long_text)]))
    wrap_view.set_position(0)
    wait(100)
    wrap_view._ensure_layout()
    rows = wrap_view._rows[0]
    check(len(rows) > 1, f"回归：超长歌词自动折行（{len(rows)} 行）")
    check("".join(rows) == long_text, "回归：折行后文字完整")
    check(
        abs(wrap_view._heights[0] - len(rows) * 40) < 0.01,
        f"回归：折行后行高按行数扩展（{wrap_view._heights[0]}）",
    )
    wrap_view.deleteLater()

    # 7.10 library.json 版本迁移：v1 能读、保存升级到当前版本、内容不变不重写
    version_file = base / "versioned" / "library.json"
    version_file.parent.mkdir(parents=True)
    version_file.write_text(
        json.dumps({"folders": [str(music)], "tracks": [], "favorites": [], "playlists": []}),
        encoding="utf-8",
    )
    old_lib = Library()
    old_lib.file = version_file
    old_lib.folders, old_lib.tracks, old_lib.favorites, old_lib.playlists = [], {}, set(), []
    old_lib.extra_files = []
    old_lib.load()
    check(old_lib.folders == [str(music)], "回归：v1 曲库（无 extra_files 字段）能正常读取")
    old_lib.save()
    saved = json.loads(version_file.read_text(encoding="utf-8"))
    check(
        saved.get("version") == LAYOUT_VERSION and saved.get("extra_files") == [],
        f"回归：保存时升级到 v{LAYOUT_VERSION}",
    )
    version_stamp = version_file.stat().st_mtime_ns
    old_lib.save()
    check(
        version_file.stat().st_mtime_ns == version_stamp,
        "回归：内容没变时不重写 library.json",
    )

    # 7.11 写盘失败要上报，不能静默吞掉
    fail_lib = Library()
    fail_lib.file = base / "missing_dir" / "library.json"
    save_errors: list[str] = []
    fail_lib.saveFailed.connect(lambda msg: save_errors.append(msg))
    fail_lib.folders = [str(music)]
    fail_lib.save()
    check(bool(save_errors), f"回归：写盘失败会上报（{len(save_errors)} 次）")

    window.select_view(window.VIEW_ALL)
    wait(200)

    # ================================================ 收尾
    window.grab().save(str(ROOT / "docs" / "preview_features.png"))
    window._tray_enabled = False
    window.close()
    wait(300)
    shutil.rmtree(base, ignore_errors=True)

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    if failed:
        print("失败项：")
        for label in failed:
            print(" -", label)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
