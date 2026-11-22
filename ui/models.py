"""歌曲表格模型与搜索过滤代理。"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont

from core.metadata import Track
from core.utils import fmt_duration

from .icons import make_icon
from .theme import ACCENT, MUTED

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
PATH_ROLE = Qt.ItemDataRole.UserRole + 2


class SongModel(QAbstractTableModel):
    HEADERS = ["#", "标题", "艺术家", "专辑", "时长"]

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self._library = library
        self._tracks: list[Track] = []
        self._rows: dict[str, int] = {}
        self._current = ""
        self._star = make_icon("star", ACCENT, 13)
        self._base_font = QFont()

    def set_base_font(self, font) -> None:
        """记录表格实际字体，高亮行加粗时以此为基础（否则会退回默认字号）。"""
        if font is not None and font.pointSize() > 0:
            self._base_font = QFont(font)

    # ---------------------------------------------------------------- 数据
    def set_tracks(self, tracks: list[Track]) -> None:
        self.beginResetModel()
        self._tracks = list(tracks)
        self._rows = {track.path: index for index, track in enumerate(self._tracks)}
        self.endResetModel()

    def sync_tracks(self, tracks: list[Track]) -> None:
        """把内容更新到 tracks，尽量不动选中和滚动位置。

        - 完全一致：只发 dataChanged（收藏星标、播放中的高亮会跟着刷新）
        - 同一批歌换了顺序：layoutChanged + 持久索引重映射
        - 有增有删：按连续区间 beginRemoveRows / beginInsertRows，最后再校准顺序
        """
        tracks = list(tracks)
        new_paths = [t.path for t in tracks]
        old_paths = [t.path for t in self._tracks]

        if new_paths == old_paths:
            self._tracks = tracks
            self._rows = {t.path: i for i, t in enumerate(tracks)}
            self._emit_all_changed()
            return
        if set(new_paths) == set(old_paths):
            self._apply_order(tracks)
            return
        self._diff_update(tracks)

    def track_at(self, row: int) -> Track | None:
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def path_at(self, row: int) -> str:
        track = self.track_at(row)
        return track.path if track else ""

    def row_of(self, path: str) -> int:
        return self._rows.get(path, -1)

    def set_current(self, path: str) -> None:
        old = self._current
        self._current = path or ""
        for target in (old, self._current):
            row = self.row_of(target)
            if row >= 0:
                self.dataChanged.emit(
                    self.index(row, 0),
                    self.index(row, len(self.HEADERS) - 1),
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole,
                     Qt.ItemDataRole.FontRole],
                )

    def refresh_favorites(self) -> None:
        if not self._tracks:
            return
        self.dataChanged.emit(
            self.index(0, 1),
            self.index(len(self._tracks) - 1, 1),
            [Qt.ItemDataRole.DecorationRole],
        )

    def move_paths(self, paths: list[str], anchor_path: str | None = None) -> bool:
        """把 paths 整体移动到 anchor_path 之后（None 表示移到最前）。

        保持选中状态与滚动位置：用 layoutChanged + 持久索引重映射，
        而不是整表 reset。
        """
        wanted = set(paths)
        moving = [t for t in self._tracks if t.path in wanted]
        if not moving or len(moving) == len(self._tracks):
            return False
        rest = [t for t in self._tracks if t.path not in wanted]
        if anchor_path is None:
            index = 0
        else:
            found = next(
                (i for i, t in enumerate(rest) if t.path == anchor_path), -1
            )
            index = found + 1 if found >= 0 else len(rest)
        order = rest[:index] + moving + rest[index:]
        if [t.path for t in order] == [t.path for t in self._tracks]:
            return False

        self._apply_order(order)
        return True

    def _apply_order(self, order: list[Track]) -> None:
        """重排现有行（集合不变），用 layoutChanged 保住选中与滚动。"""
        old_paths = [t.path for t in self._tracks]
        positions = {t.path: i for i, t in enumerate(order)}
        persistent = self.persistentIndexList()

        self.layoutAboutToBeChanged.emit()
        self._tracks = order
        self._rows = dict(positions)
        for item in persistent:
            if not item.isValid():
                continue
            row = positions.get(old_paths[item.row()])
            if row is not None:
                self.changePersistentIndex(item, self.index(row, item.column()))
        self.layoutChanged.emit()

        self._emit_all_changed()

    def _diff_update(self, tracks: list[Track]) -> None:
        """按连续区间删旧行、插新行，其余行保持不动。"""
        wanted = {t.path for t in tracks}

        # 1) 删掉新列表里没有的行（从后往前，连续段合并成一次 removeRows）
        row = len(self._tracks) - 1
        while row >= 0:
            if self._tracks[row].path in wanted:
                row -= 1
                continue
            end = row
            while row >= 0 and self._tracks[row].path not in wanted:
                row -= 1
            start = row + 1
            self.beginRemoveRows(QModelIndex(), start, end)
            del self._tracks[start:end + 1]
            self.endRemoveRows()

        # 2) 插入列表里还没有的行
        have = {t.path for t in self._tracks}
        index = 0
        while index < len(tracks):
            if tracks[index].path in have:
                index += 1
                continue
            end = index
            while end + 1 < len(tracks) and tracks[end + 1].path not in have:
                end += 1
            self.beginInsertRows(QModelIndex(), index, end)
            self._tracks[index:index] = tracks[index:end + 1]
            self.endInsertRows()
            index = end + 1

        # 3) 集合现在一致了，但相对顺序可能和期望不同（新歌插在了末尾）
        if [t.path for t in self._tracks] != [t.path for t in tracks]:
            self._apply_order(tracks)
        else:
            self._tracks = list(tracks)
            self._rows = {t.path: i for i, t in enumerate(self._tracks)}
            self._emit_all_changed()

    def _emit_all_changed(self) -> None:
        if not self._tracks:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._tracks) - 1, len(self.HEADERS) - 1),
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole,
             Qt.ItemDataRole.FontRole, Qt.ItemDataRole.DecorationRole],
        )

    # ---------------------------------------------------------------- Qt 接口
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tracks)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                if section in (0, 4):
                    return int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        track = self.track_at(index.row())
        if track is None:
            return None
        column = index.column()
        is_current = track.path == self._current

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return "\u266a" if is_current else str(index.row() + 1)
            if column == 1:
                return track.title
            if column == 2:
                return track.artist
            if column == 3:
                return track.album
            if column == 4:
                return fmt_duration(track.duration)
            return None

        if role == SORT_ROLE:
            if column == 0:
                return index.row()
            if column == 1:
                return track.title.lower()
            if column == 2:
                return track.artist.lower()
            if column == 3:
                return track.album.lower()
            return track.duration

        if role == PATH_ROLE:
            return track.path

        if role == Qt.ItemDataRole.DecorationRole and column == 1:
            if self._library.is_favorite(track.path):
                return self._star
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (0, 4):
                return int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if is_current:
                return QColor(ACCENT)
            if column == 0:
                return QColor(MUTED)
            return None

        if role == Qt.ItemDataRole.FontRole and is_current:
            font = QFont(self._base_font)
            font.setBold(True)
            return font

        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [track.title, f"{track.artist} · {track.album}",
                     fmt_duration(track.duration), track.path]
            return "\n".join(p for p in parts if p)
        return None


class TrackFilterProxy(QSortFilterProxyModel):
    """多关键字（空格分隔）匹配歌名 / 艺术家 / 专辑。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        try:
            self.setSortLocaleAware(True)   # 字符串排序跟随系统语言环境
        except AttributeError:
            pass
        self._tokens: list[str] = []

    def set_query(self, text: str) -> None:
        tokens = [t for t in (text or "").lower().split() if t]
        if tokens == self._tokens:
            return
        self._tokens = tokens
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._tokens:
            return True
        model = self.sourceModel()
        track = model.track_at(source_row) if model else None
        if track is None:
            return False
        haystack = f"{track.title} {track.artist} {track.album} {track.stem}".lower()
        return all(token in haystack for token in self._tokens)
