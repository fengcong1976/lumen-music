"""通用小工具。"""
from __future__ import annotations

import re

_NUMBER = re.compile(r"(\d+)")


def natural_key(text: str) -> list:
    """自然排序键：把「第 10 首」排在「第 9 首」之后。"""
    parts = _NUMBER.split(str(text).lower())
    return [int(part) if part.isdigit() else part for part in parts]


def fmt_time(ms: int) -> str:
    """毫秒 -> m:ss / h:mm:ss"""
    try:
        total = int(max(0, ms) // 1000)
    except (TypeError, ValueError):
        total = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_duration(seconds: int) -> str:
    return fmt_time(int(seconds or 0) * 1000)


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"
