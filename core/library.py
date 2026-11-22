"""媒体库：扫描音乐文件夹、缓存元数据、管理播放列表与收藏。"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .metadata import Track, is_audio, read_track
from .paths import data_dir

LAYOUT_VERSION = 2      # library.json 的结构版本，读到更高的版本会先备份再继续


@dataclass
class Playlist:
    id: str
    name: str
    tracks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "tracks": list(self.tracks)}


def path_within(path: str, folder: str) -> bool:
    """path 是否位于 folder 之内（按目录边界比较）。

    只做 startswith 会把 `…\\Music2` 当成 `…\\Music` 的子项，
    移除文件夹时就会连累同名兄弟目录。
    """
    child = os.path.normcase(os.path.normpath(path))
    parent = os.path.normcase(os.path.normpath(folder))
    if parent.endswith(os.sep):
        return child.startswith(parent)
    return child == parent or child.startswith(parent + os.sep)


def _migrate(data: dict, version: int) -> dict:
    """把旧版本的数据补成当前结构（缺字段给默认值，不动多余字段）。"""
    if version < 2:
        # v1 还没有「拖进来的单曲」列表
        data.setdefault("extra_files", [])
    return data


class Library(QObject):
    changed = Signal()
    saveFailed = Signal(str)     # 写盘失败（磁盘满、权限不足……）时通知界面

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file = data_dir() / "library.json"
        self.folders: list[str] = []
        self.extra_files: list[str] = []
        self.tracks: dict[str, Track] = {}
        self.favorites: set[str] = set()
        self.playlists: list[Playlist] = []
        self._rev = 0
        self._sorted: tuple[int, int, list[Track]] | None = None
        self._last_saved: str | None = None
        self.load()

    # ---------------------------------------------------------------- 持久化
    def load(self) -> None:
        if not self.file.exists():
            return
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        version = self._read_version(data)
        if version > LAYOUT_VERSION:
            # 这份文件来自更新版本的程序：先留一份备份，免得我们的保存把它降级覆盖
            self._backup_newer(version)
        data = _migrate(data, version)
        self.folders = [str(Path(p)) for p in data.get("folders", []) if p]
        self.extra_files = [str(Path(p)) for p in data.get("extra_files", []) if p]
        for item in data.get("tracks", []):
            track = Track.from_dict(item)
            if track.path:
                self.tracks[track.path] = track
        self.favorites = {p for p in data.get("favorites", []) if p}
        for item in data.get("playlists", []):
            try:
                self.playlists.append(
                    Playlist(
                        id=item.get("id") or uuid.uuid4().hex[:8],
                        name=item.get("name") or "未命名列表",
                        tracks=[str(p) for p in item.get("tracks", []) if p],
                    )
                )
            except Exception:
                continue

    @staticmethod
    def _read_version(data: dict) -> int:
        try:
            return int(data.get("version") or 1)
        except (TypeError, ValueError):
            return 1

    def _backup_newer(self, version: int) -> None:
        backup = self.file.with_suffix(f".v{version}.bak")
        if backup.exists():
            return
        try:
            backup.write_bytes(self.file.read_bytes())
        except OSError:
            pass

    def save(self) -> None:
        self._rev += 1          # 所有改动都会经过 save()，用它给排序缓存失效
        payload = {
            "version": LAYOUT_VERSION,
            "folders": self.folders,
            "extra_files": self.extra_files,
            "tracks": [t.to_dict() for t in self.tracks.values()],
            "favorites": sorted(self.favorites),
            "playlists": [p.to_dict() for p in self.playlists],
        }
        try:
            text = json.dumps(payload, ensure_ascii=False, indent=1)
        except (TypeError, ValueError):
            return
        if text == self._last_saved:
            return              # 内容没变就别重写整份文件
        tmp = self.file.with_suffix(".tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.file)
        except OSError as exc:
            self.saveFailed.emit(f"保存曲库失败：{exc}")
            return
        self._last_saved = text

    # ---------------------------------------------------------------- 文件夹
    def add_folder(self, path: str) -> bool:
        path = str(Path(path).resolve())
        if not os.path.isdir(path):
            return False
        if any(os.path.normcase(f) == os.path.normcase(path) for f in self.folders):
            return False
        # 避免重复扫描父/子目录
        if any(path_within(path, existing) for existing in self.folders):
            return False
        self.folders.append(path)
        self.save()
        return True

    def remove_folder(self, path: str) -> int:
        """移除扫描目录，并清掉它下面的曲目、收藏与列表条目（不动硬盘文件）。

        返回被移出曲库的歌曲数。
        """
        self.folders = [f for f in self.folders if not path_within(f, path)]
        self.extra_files = [p for p in self.extra_files if not path_within(p, path)]
        dropped = {p for p in self.tracks if path_within(p, path)}
        for key in dropped:
            self.tracks.pop(key, None)
        self.favorites -= dropped
        for playlist in self.playlists:
            playlist.tracks = [p for p in playlist.tracks if p not in dropped]
        self.save()
        self.changed.emit()
        return len(dropped)

    def add_files(self, paths: list[str]) -> int:
        added = 0
        known = {os.path.normcase(p) for p in self.extra_files}
        for path in paths:
            if not is_audio(path) or not os.path.isfile(path):
                continue
            resolved = str(Path(path).resolve())
            if os.path.normcase(resolved) in known:
                continue
            self.extra_files.append(resolved)
            known.add(os.path.normcase(resolved))
            added += 1
        if added:
            self.save()
        return added

    def known_snapshot(self) -> dict[str, dict]:
        return {path: track.to_dict() for path, track in self.tracks.items()}

    def apply_scan(self, scanned: list[Track]) -> int:
        """用一次扫描结果替换曲库；保留首次入库时间。"""
        previous = self.tracks
        merged: dict[str, Track] = {}
        now = time.time()
        for track in scanned:
            old = previous.get(track.path)
            track.added = (old.added if old and old.added else now)
            merged[track.path] = track
        # 扫描进行中新拖入的文件不在本次结果里，但文件仍在硬盘上：
        # 这些条目要原样留在曲库里（下一次扫描会把它们补全），
        # 否则刚建的播放列表会在扫描结束时短暂变空。
        keep = [p for p in previous if p not in merged and os.path.isfile(p)]
        for path in keep:
            merged[path] = previous[path]
        self.tracks = merged
        # 清掉真的已不存在的收藏 / 列表条目。
        self.favorites = {p for p in self.favorites if p in merged}
        for playlist in self.playlists:
            playlist.tracks = [p for p in playlist.tracks if p in merged]
        self.save()
        self.changed.emit()
        return len(merged)

    def merge_tracks(self, tracks: list[Track]) -> int:
        """只新增 / 更新给定歌曲，不删除其它条目。

        拖拽播放时用：文件立刻进库，不必等后台全量扫描结束。
        """
        if not tracks:
            return 0
        now = time.time()
        for track in tracks:
            old = self.tracks.get(track.path)
            track.added = old.added if old and old.added else now
            self.tracks[track.path] = track
        self.save()
        self.changed.emit()
        return len(tracks)

    # ---------------------------------------------------------------- 查询
    def all_tracks(self) -> list[Track]:
        # 搜索每敲一个键都会走到这里，1 万首全排一次太浪费，按版本号缓存。
        key = (self._rev, len(self.tracks))
        if self._sorted is not None and self._sorted[:2] == key:
            return list(self._sorted[2])
        ordered = sorted(
            self.tracks.values(),
            key=lambda t: (t.artist.lower(), t.album.lower(), t.track_no, t.title.lower()),
        )
        self._sorted = (key[0], key[1], ordered)
        return list(ordered)

    def recent_tracks(self) -> list[Track]:
        return sorted(self.tracks.values(), key=lambda t: t.added, reverse=True)

    def favorite_tracks(self) -> list[Track]:
        return [t for t in self.all_tracks() if t.path in self.favorites]

    def get(self, path: str) -> Track | None:
        return self.tracks.get(path)

    def playlist(self, playlist_id: str) -> Playlist | None:
        for playlist in self.playlists:
            if playlist.id == playlist_id:
                return playlist
        return None

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        playlist = self.playlist(playlist_id)
        if playlist is None:
            return []
        return [self.tracks[p] for p in playlist.tracks if p in self.tracks]

    def count_of(self, playlist_id: str) -> int:
        playlist = self.playlist(playlist_id)
        if playlist is None:
            return 0
        return len([p for p in playlist.tracks if p in self.tracks])

    # ---------------------------------------------------------------- 收藏
    def is_favorite(self, path: str) -> bool:
        return path in self.favorites

    def toggle_favorite(self, path: str) -> bool:
        if path in self.favorites:
            self.favorites.discard(path)
            state = False
        else:
            self.favorites.add(path)
            state = True
        self.save()
        return state

    def set_favorites(self, paths: list[str], state: bool) -> int:
        """批量设置收藏，只写一次 library.json；返回真正变化的数量。"""
        changed = 0
        for path in paths:
            if state and path not in self.favorites:
                self.favorites.add(path)
                changed += 1
            elif not state and path in self.favorites:
                self.favorites.discard(path)
                changed += 1
        if changed:
            self.save()
        return changed

    # ---------------------------------------------------------------- 播放列表
    def create_playlist(self, name: str, tracks: list[str] | None = None) -> Playlist:
        playlist = Playlist(
            id=uuid.uuid4().hex[:8],
            name=name.strip() or "新建列表",
            tracks=list(tracks or []),
        )
        self.playlists.append(playlist)
        self.save()
        self.changed.emit()
        return playlist

    def rename_playlist(self, playlist_id: str, name: str) -> None:
        playlist = self.playlist(playlist_id)
        if playlist is None or not name.strip():
            return
        playlist.name = name.strip()
        self.save()
        self.changed.emit()

    def delete_playlist(self, playlist_id: str) -> None:
        self.playlists = [p for p in self.playlists if p.id != playlist_id]
        self.save()
        self.changed.emit()

    def add_to_playlist(self, playlist_id: str, paths: list[str]) -> int:
        playlist = self.playlist(playlist_id)
        if playlist is None:
            return 0
        existing = set(playlist.tracks)
        added = 0
        for path in paths:
            if path in self.tracks and path not in existing:
                playlist.tracks.append(path)
                existing.add(path)
                added += 1
        if added:
            self.save()
            self.changed.emit()
        return added

    def remove_from_playlist(self, playlist_id: str, paths: list[str]) -> int:
        playlist = self.playlist(playlist_id)
        if playlist is None:
            return 0
        drop = set(paths)
        before = len(playlist.tracks)
        playlist.tracks = [p for p in playlist.tracks if p not in drop]
        removed = before - len(playlist.tracks)
        if removed:
            self.save()
            self.changed.emit()
        return removed

    def move_in_playlist(
        self, playlist_id: str, paths: list[str], anchor_path: str | None = None
    ) -> bool:
        """把 paths 整体移动到 anchor_path 之后（None 表示移到最前）。"""
        playlist = self.playlist(playlist_id)
        if playlist is None:
            return False
        moving = [p for p in playlist.tracks if p in set(paths)]
        if not moving:
            return False
        rest = [p for p in playlist.tracks if p not in set(paths)]
        if anchor_path is None:
            index = 0
        else:
            try:
                index = rest.index(anchor_path) + 1
            except ValueError:
                index = len(rest)
        reordered = rest[:index] + moving + rest[index:]
        if reordered == playlist.tracks:
            return False
        playlist.tracks = reordered
        self.save()
        return True

    # ---------------------------------------------------------------- 扫描
    def needs_scan(self) -> bool:
        return bool(self.folders or self.extra_files) and not self.tracks

    def scan_sources(self) -> tuple[list[str], list[str]]:
        return list(self.folders), [p for p in self.extra_files if os.path.isfile(p)]


def cached_track(path: str, known: dict[str, dict]) -> Track | None:
    """命中缓存（mtime + size 未变）时直接复用，避免重复解析标签。"""
    cached = known.get(path)
    if not cached:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    if (abs(cached.get("mtime", 0) - stat.st_mtime) < 1e-6
            and cached.get("size") == stat.st_size):
        return Track.from_dict(cached)
    return None


def load_tracks(files: list[str], known: dict[str, dict], progress=None,
                stop=None) -> list[Track]:
    """按给定顺序读取一批文件的元数据（带缓存），读不出的文件跳过。"""
    tracks: list[Track] = []
    total = len(files)
    for index, path in enumerate(files):
        if stop is not None and stop():
            break
        track = cached_track(path, known)
        if track is None:
            try:
                track = read_track(path)
            except Exception:
                track = None
        if track is not None:
            tracks.append(track)
        if progress is not None:
            progress(index + 1, total)
    return tracks


class TrackLoader(QThread):
    """后台读取指定文件列表的元数据（拖拽播放时用，避免界面卡住）。"""

    progress = Signal(int, int)
    finished_ok = Signal(list)

    def __init__(self, files: list[str], known: dict[str, dict], parent=None):
        super().__init__(parent)
        self._files = list(files)
        self._known = known
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        tracks = load_tracks(
            self._files, self._known, self.progress.emit, lambda: self._stop
        )
        if not self._stop:
            self.finished_ok.emit(tracks)


class ScanWorker(QThread):
    """后台扫描线程：遍历目录、读取元数据（带缓存）。"""

    progress = Signal(int, int, str)
    found = Signal(int)
    finished_ok = Signal(list)

    def __init__(self, folders: list[str], extra_files: list[str],
                 known: dict[str, dict], parent=None):
        super().__init__(parent)
        self._folders = folders
        self._extra_files = extra_files
        self._known = known
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def _collect(self) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()

        def push(path: str) -> None:
            key = os.path.normcase(path)
            if key not in seen:
                seen.add(key)
                files.append(path)

        for folder in self._folders:
            if self._stop or not os.path.isdir(folder):
                continue
            for root, dirs, names in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in names:
                    if is_audio(name):
                        push(os.path.join(root, name))
                if self._stop:
                    break
        for path in self._extra_files:
            if os.path.isfile(path):
                push(path)
        return files

    def run(self) -> None:
        files = self._collect()
        total = len(files)
        self.found.emit(total)
        result: list[Track] = []

        for index, path in enumerate(files):
            if self._stop:
                break
            track = cached_track(path, self._known)
            if track is None:
                try:
                    track = read_track(path)
                except Exception:
                    track = None
            if track is not None:
                result.append(track)
            if index % 20 == 0 or index == total - 1:
                self.progress.emit(index + 1, total, os.path.basename(path))

        # 被要求停止时结果是不完整的，绝不能拿去替换曲库（否则会误删条目）。
        if not self._stop:
            self.finished_ok.emit(result)
