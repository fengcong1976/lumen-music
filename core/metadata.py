"""音频文件元数据读取（标题 / 艺术家 / 专辑 / 时长 / 封面）。"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

AUDIO_EXTS = {
    ".mp3", ".flac", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus",
    ".wav", ".wma", ".ape", ".aiff", ".aif", ".alac", ".wv", ".dsf", ".dff",
}

UNKNOWN_ARTIST = "未知艺术家"
UNKNOWN_ALBUM = "未知专辑"


def is_audio(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTS


@dataclass
class Track:
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: int = 0          # 秒
    track_no: int = 0
    year: str = ""
    mtime: float = 0.0
    size: int = 0
    added: float = 0.0

    @property
    def filename(self) -> str:
        return Path(self.path).name

    @property
    def stem(self) -> str:
        """不含扩展名的文件名（搜索时也能按文件名找歌）。"""
        return Path(self.path).stem

    @property
    def folder(self) -> str:
        return str(Path(self.path).parent)

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Track":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def __str__(self) -> str:
        return f"{self.title} - {self.artist}"


def _open(path: str, easy: bool):
    from mutagen import File as MutagenFile

    return MutagenFile(path, easy=easy)


def _first(value) -> str:
    """标签值可能是 str / list / ID3 Frame，统一取出第一段文本。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _tag_text(tags, keys) -> str:
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:
            continue
        text = _first(value)
        if text:
            return text
    return ""


def _guess_from_filename(stem: str) -> tuple[str, str]:
    """从 '01. 艺术家 - 歌名' 这类文件名里猜标题与艺术家。"""
    cleaned = re.sub(r"^\s*\d{1,3}[\s._\-]+(?=\S)", "", stem).strip()
    for sep in (" - ", " – ", " — ", "-", "_"):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            if left.strip() and right.strip():
                return right.strip(), left.strip()
    return cleaned.strip(), ""


def read_track(path: str) -> Track:
    p = Path(path)
    try:
        stat = p.stat()
        mtime, size = stat.st_mtime, stat.st_size
    except OSError:
        mtime, size = 0.0, 0

    title = artist = album = year = ""
    duration = 0
    track_no = 0

    audio = None
    for easy in (True, False):
        try:
            audio = _open(path, easy)
        except Exception:
            audio = None
        if audio is not None:
            break

    if audio is not None:
        info = getattr(audio, "info", None)
        if info is not None:
            try:
                duration = int(round(float(getattr(info, "length", 0) or 0)))
            except Exception:
                duration = 0
        tags = getattr(audio, "tags", None)
        if tags is not None:
            title = _tag_text(tags, ("title", "TIT2", "\xa9nam", "Title"))
            artist = _tag_text(
                tags, ("artist", "TPE1", "\xa9ART", "albumartist", "AlbumArtist")
            )
            album = _tag_text(tags, ("album", "TALB", "\xa9alb", "Album"))
            year = _tag_text(tags, ("date", "TDRC", "\xa9day", "Date"))[:4]
            raw_track = _tag_text(tags, ("tracknumber", "TRCK", "trkn", "TrackNumber"))
            digits = re.match(r"\s*(\d+)", raw_track or "")
            if digits:
                track_no = int(digits.group(1))

    if not title or not artist:
        guess_title, guess_artist = _guess_from_filename(p.stem)
        title = title or guess_title
        artist = artist or guess_artist

    return Track(
        path=str(p),
        title=title or p.stem,
        artist=artist or UNKNOWN_ARTIST,
        album=album or UNKNOWN_ALBUM,
        duration=duration,
        track_no=track_no,
        year=year,
        mtime=mtime,
        size=size,
    )


def open_audio(path: str, easy: bool = False):
    """打开音频标签对象；失败返回 None。

    切歌时要同时拿封面和内嵌歌词，只打开一次就够了。
    """
    try:
        return _open(path, easy)
    except Exception:
        return None


def read_cover_from(audio) -> bytes | None:
    """从已打开的 mutagen 对象里取内嵌封面。"""
    if audio is None:
        return None

    tags = getattr(audio, "tags", None)

    # ID3 (mp3)
    try:
        if tags is not None and hasattr(tags, "getall"):
            pictures = tags.getall("APIC")
            if pictures:
                return pictures[0].data
    except Exception:
        pass

    # FLAC
    pictures = getattr(audio, "pictures", None)
    if pictures:
        try:
            return pictures[0].data
        except Exception:
            pass

    if tags is not None:
        # MP4
        try:
            covr = tags.get("covr")
            if covr:
                return bytes(covr[0])
        except Exception:
            pass
        # Ogg / Vorbis
        try:
            block = tags.get("metadata_block_picture")
            if block:
                import base64

                from mutagen.flac import Picture

                raw = block[0] if isinstance(block, (list, tuple)) else block
                return Picture(base64.b64decode(raw)).data
        except Exception:
            pass
    return None
