"""LRC 歌词解析与查找。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve|tool):(.*)\]$", re.I)
_WORD_TAG = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")


@dataclass
class LyricLine:
    time: int          # 毫秒
    text: str


@dataclass
class Lyrics:
    lines: list[LyricLine] = field(default_factory=list)
    plain: bool = False        # 无时间轴（纯文本歌词）
    source: str = ""
    offset: int = 0

    @property
    def empty(self) -> bool:
        return not self.lines


def _fraction(value: str | None) -> int:
    if not value:
        return 0
    if len(value) == 1:
        return int(value) * 100
    if len(value) == 2:
        return int(value) * 10
    return int(value[:3])


def parse_lrc(text: str, source: str = "", offset: int = 0) -> Lyrics:
    lines: list[LyricLine] = []

    for raw in text.splitlines():
        line = raw.replace("\ufeff", "").strip()
        if not line:
            continue

        meta = _META_TAG.match(line)
        if meta:
            if meta.group(1).lower() == "offset":
                try:
                    offset = int(float(meta.group(2).strip()))
                except ValueError:
                    pass
            continue

        stamps = list(_TIME_TAG.finditer(line))
        if not stamps:
            continue

        content = line[stamps[-1].end():]
        content = _WORD_TAG.sub("", content).strip()
        for stamp in stamps:
            ms = (
                int(stamp.group(1)) * 60000
                + int(stamp.group(2)) * 1000
                + _fraction(stamp.group(3))
            )
            lines.append(LyricLine(max(0, ms - offset), content))

    lines.sort(key=lambda item: item.time)

    # 同一时间点重复行去重
    deduped: list[LyricLine] = []
    for line in lines:
        if deduped and deduped[-1].time == line.time and deduped[-1].text == line.text:
            continue
        deduped.append(line)
    return Lyrics(lines=deduped, plain=False, source=source, offset=offset)


def _plain(text: str, source: str) -> Lyrics:
    lines = [LyricLine(0, line.strip()) for line in text.splitlines() if line.strip()]
    return Lyrics(lines=lines, plain=True, source=source)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _embedded_lyrics(path: str, audio=None) -> str:
    if audio is None:
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(path)
        except Exception:
            return ""
    if audio is None:
        return ""

    tags = getattr(audio, "tags", None)
    if tags is not None:
        try:
            if hasattr(tags, "getall"):
                frames = tags.getall("USLT")
                if frames:
                    return _first_text(frames[0].text)
        except Exception:
            pass
        for key in ("lyrics", "LYRICS", "unsyncedlyrics", "UNSYNCEDLYRICS",
                    "\xa9lyr", "USLT", "LYRICS-eng"):
            try:
                value = tags.get(key)
            except Exception:
                continue
            text = _first_text(value)
            if text:
                return text

    try:
        value = audio.get("LYRICS") or audio.get("lyrics")
        text = _first_text(value)
        if text:
            return text
    except Exception:
        pass
    return ""


def _first_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _lrc_candidates(track_path: str) -> list[Path]:
    p = Path(track_path)
    stem_lower = p.stem.lower()
    folders = [p.parent, p.parent / "lyrics", p.parent / "Lyrics", p.parent / "歌词"]

    # 快路径：绝大多数情况就是同目录下同名 .lrc，最多 4 次 stat。
    direct: list[Path] = []
    for folder in folders:
        candidate = folder / f"{p.stem}.lrc"
        if candidate.is_file():
            direct.append(candidate)
    if direct:
        return direct

    # 慢路径：文件名大小写/扩展名不一致时才扫目录，避免每次切歌都遍历整目录。
    candidates: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            for child in folder.iterdir():
                if child.is_file() and child.suffix.lower() == ".lrc" \
                        and child.stem.lower() == stem_lower:
                    candidates.append(child)
        except OSError:
            continue
    return candidates


def find_lyrics(track_path: str, audio=None) -> Lyrics | None:
    """优先同名 .lrc 文件，其次内嵌歌词，都没有返回 None。

    audio 可以传入已打开的 mutagen 对象，省一次文件解析。
    """
    for candidate in _lrc_candidates(track_path):
        try:
            text = _decode(candidate.read_bytes())
        except OSError:
            continue
        lyrics = parse_lrc(text, source=candidate.name)
        if lyrics.lines:
            return lyrics
        if text.strip():
            return _plain(text, candidate.name)

    embedded = _embedded_lyrics(track_path, audio=audio)
    if embedded:
        if _TIME_TAG.search(embedded):
            lyrics = parse_lrc(embedded, source="内嵌歌词")
            if lyrics.lines:
                return lyrics
        return _plain(embedded, "内嵌歌词")
    return None
