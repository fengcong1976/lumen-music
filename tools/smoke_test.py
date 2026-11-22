"""端到端冒烟测试：生成测试音频与 LRC，验证扫描/播放/歌词/搜索/播放列表。

用法：venv/Scripts/python.exe tools/smoke_test.py
"""
from __future__ import annotations

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

from PySide6.QtCore import QCoreApplication, QEventLoop, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import ui.main_window as main_window_module  # noqa: E402
from core.library import Library, ScanWorker  # noqa: E402
from core.lyrics import find_lyrics  # noqa: E402
from core.metadata import read_track  # noqa: E402
from core.player import PlayMode, Player  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import QSS, apply_font  # noqa: E402

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


def make_wav(path: Path, freq: float, seconds: float = 6.0, rate: int = 22050) -> None:
    total = int(seconds * rate)
    buffer = bytearray()
    fade = max(1, int(0.03 * rate))
    for index in range(total):
        env = min(1.0, index / fade, (total - index) / fade)
        sample = int(11000 * env * math.sin(2 * math.pi * freq * index / rate))
        buffer += struct.pack("<h", sample)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(buffer))


LRC_TEXT = """[ti:夜色电台]
[ar:测试艺术家]
[offset:0]
[00:00.00]夜色电台 - 测试艺术家
[00:02.00]第一句歌词在第二秒
[00:03.50]第二句歌词在三点五秒
[00:05.00]第三句歌词在第五秒
[00:06.50]最后一句歌词
"""


def build_fixtures(base: Path) -> Path:
    music = base / "音乐库"
    (music / "专辑A").mkdir(parents=True, exist_ok=True)
    (music / "专辑B").mkdir(parents=True, exist_ok=True)

    a = music / "专辑A" / "01. 测试艺术家 - 夜色电台.wav"
    make_wav(a, 440.0)
    a.with_suffix(".lrc").write_text(LRC_TEXT, encoding="utf-8")

    b = music / "专辑A" / "02. 测试艺术家 - 清晨地铁.wav"
    make_wav(b, 523.25, 5.0)

    c = music / "专辑B" / "Lumen - 雨后的街道.wav"
    make_wav(c, 349.23, 4.0)
    return music


def main() -> int:
    QCoreApplication.setOrganizationName("LumenAudio")
    QCoreApplication.setApplicationName("LumenSmoke")
    app = QApplication(sys.argv)
    apply_font(app)
    app.setStyleSheet(QSS)

    base = Path(tempfile.mkdtemp(prefix="lumen_smoke_"))
    isolate_settings(base)
    music = build_fixtures(base)

    # ---- 元数据 ----
    track = read_track(str(music / "专辑A" / "01. 测试艺术家 - 夜色电台.wav"))
    check(track.title == "夜色电台", f"文件名解析标题: {track.title}")
    check(track.artist == "测试艺术家", f"文件名解析艺术家: {track.artist}")
    check(5 <= track.duration <= 7, f"读取时长: {track.duration}s")

    # ---- 歌词 ----
    lyrics = find_lyrics(str(music / "专辑A" / "01. 测试艺术家 - 夜色电台.wav"))
    check(lyrics is not None and len(lyrics.lines) == 5, f"解析 LRC 行数: {lyrics and len(lyrics.lines)}")
    check(lyrics is not None and lyrics.lines[1].time == 2000, "LRC 时间轴正确")

    # ---- 音乐库 ----
    library = Library()
    library.file = base / "library.json"
    library.folders = []
    library.extra_files = []
    library.tracks = {}
    library.favorites = set()
    library.playlists = []
    check(library.add_folder(str(music)), "添加音乐文件夹")

    scanned: list = []
    worker = ScanWorker(library.folders, [], {}, None)
    worker.finished_ok.connect(lambda tracks: scanned.extend(tracks))
    worker.run()
    library.apply_scan(scanned)
    check(len(scanned) == 3, f"扫描到 {len(scanned)} 首歌曲")
    check(len(library.all_tracks()) == 3, "曲库数量正确")

    # ---- 界面 ----
    player = Player()
    player.set_volume(10)
    window = MainWindow(library, player)
    window.resize(1280, 820)
    window.show()
    wait(400)
    check(window.proxy.rowCount() == 3, f"列表显示 {window.proxy.rowCount()} 行")

    # ---- 播放 ----
    target_row = 0
    for row in range(window.proxy.rowCount()):
        source = window.proxy.mapToSource(window.proxy.index(row, 0))
        if "夜色电台" in window.model.path_at(source.row()):
            target_row = row
            break
    window._on_row_activated(window.proxy.index(target_row, 0))
    wait(2500)
    check(player.is_playing, "播放状态正常")
    check(player.position() > 500, f"播放进度推进: {player.position()}ms")
    check(player.duration() >= 5500, f"播放器时长: {player.duration()}ms")
    check(window.lyrics._synced, "歌词已同步加载")
    check(window.lyrics._current >= 0, f"歌词当前行: {window.lyrics._current}")

    player.seek(5200)
    wait(700)
    check(window.lyrics._current >= 2, f"seek 后歌词行跟进: {window.lyrics._current}")
    window.grab().save(str(ROOT / "docs" / "preview.png"))

    # ---- 循环模式 ----
    player.set_mode(PlayMode.SHUFFLE)
    check(player.mode is PlayMode.SHUFFLE, "切换到随机播放")
    check(window.btn_mode.toolTip().endswith("（点击切换）"), "模式按钮提示更新")
    player.set_mode(PlayMode.LOOP_ONE)
    current_path = player.current_track.path
    player.next(manual=True)
    check(player.current_track.path != current_path, "单曲循环下手动切歌仍然换歌")
    player.next(manual=False)
    player.set_mode(PlayMode.LOOP_ALL)

    # ---- 搜索 ----
    window.search.setText("测试艺术家")
    wait(150)
    check(window.proxy.rowCount() == 2, f"按艺术家搜索: {window.proxy.rowCount()} 首")
    window.search.setText("雨后的街道")
    wait(150)
    check(window.proxy.rowCount() == 1, f"按歌名搜索: {window.proxy.rowCount()} 首")
    window.search.setText("不存在的关键词")
    wait(150)
    check(window.proxy.rowCount() == 0, "无结果为空")
    check(window.stack.currentIndex() == 1, "无结果时显示空状态")
    window.search.clear()
    wait(150)
    check(window.proxy.rowCount() == 3, "清空搜索恢复列表")

    # ---- 播放列表 ----
    playlist = library.create_playlist("我的测试歌单", [t.path for t in library.all_tracks()[:2]])
    window.select_view(window.VIEW_PLAYLIST, playlist.id)
    wait(150)
    check(window.proxy.rowCount() == 2, f"播放列表视图: {window.proxy.rowCount()} 首")
    added = library.add_to_playlist(playlist.id, [library.all_tracks()[2].path])
    check(added == 1, "向播放列表添加歌曲")
    window.select_view(window.VIEW_PLAYLIST, playlist.id)
    wait(100)
    check(window.proxy.rowCount() == 3, "播放列表数量更新")

    # ---- 收藏 ----
    library.toggle_favorite(library.all_tracks()[0].path)
    window.select_view(window.VIEW_FAVORITES)
    wait(100)
    check(window.proxy.rowCount() == 1, "收藏视图过滤正确")

    # ---- 命令行打开（文件关联入口）----
    window.select_view(window.VIEW_ALL)
    window.search.clear()
    wait(100)
    player.stop()
    window.open_paths([str(music / "专辑A" / "02. 测试艺术家 - 清晨地铁.wav")])
    wait(1500)
    check(player.is_playing, "命令行打开即播放")
    check("清晨地铁" in (player.current_track.title or ""), "命令行打开的曲目正确")
    window.open_paths([str(music / "不存在的文件夹")])
    wait(300)
    check(player.is_playing, "无有效路径时不打断正在播放")

    window.select_view(window.VIEW_ALL)
    window.search.clear()
    wait(300)
    shot = ROOT / "docs" / "preview_list.png"
    window.grab().save(str(shot))
    print(f"截图已保存: {shot}")

    player.stop()
    window._tray_enabled = False   # 测试里直接退出，不要缩到托盘
    window.close()
    wait(200)

    # ---- 空状态外观 ----
    empty_lib = Library()
    empty_lib.file = base / "empty.json"
    empty_lib.tracks = {}
    empty_lib.folders = []
    empty_lib.playlists = []
    empty_lib.favorites = set()
    empty_win = MainWindow(empty_lib, Player())
    empty_win.resize(1280, 820)
    empty_win.show()
    wait(600)
    empty_win.grab().save(str(ROOT / "docs" / "preview_empty.png"))
    empty_win._tray_enabled = False
    empty_win.close()

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
