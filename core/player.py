"""播放控制：基于 libVLC 的播放引擎（支持 10 段均衡器）、队列与循环模式。"""
from __future__ import annotations

import os
import random
import sys
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QMediaDevices, QMediaPlayer

from .metadata import Track


def _vendor_vlc() -> Path:
    """内置 VLC 运行库目录：打包后随 _internal 一起分发，开发时在项目根下。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "vendor" / "vlc"
    return Path(__file__).resolve().parents[1] / "vendor" / "vlc"


_VLC_DIR = _vendor_vlc()
if _VLC_DIR.is_dir():
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(_VLC_DIR / "libvlc.dll"))
    os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(_VLC_DIR / "plugins"))
    try:
        # Python 3.8+ 不再从 PATH 找依赖 DLL，需要显式登记目录；句柄要一直持有
        _DLL_HANDLE = os.add_dll_directory(str(_VLC_DIR))
    except (AttributeError, OSError):
        pass

import vlc  # noqa: E402

_MAIN_INSTANCE: vlc.Instance | None = None


def _instance() -> vlc.Instance:
    """全局只建一个 libVLC 实例：多开播放器会重复加载插件，启动明显变慢。"""
    global _MAIN_INSTANCE
    if _MAIN_INSTANCE is None:
        _MAIN_INSTANCE = vlc.Instance("--no-video", "--quiet", "--no-osd")
    return _MAIN_INSTANCE


class PlayMode(str, Enum):
    SEQUENTIAL = "sequential"
    LOOP_ALL = "loop_all"
    LOOP_ONE = "loop_one"
    SHUFFLE = "shuffle"


MODE_ORDER = [PlayMode.SEQUENTIAL, PlayMode.LOOP_ALL, PlayMode.LOOP_ONE, PlayMode.SHUFFLE]

MODE_LABEL = {
    PlayMode.SEQUENTIAL: "顺序播放",
    PlayMode.LOOP_ALL: "列表循环",
    PlayMode.LOOP_ONE: "单曲循环",
    PlayMode.SHUFFLE: "随机播放",
}

# VLC 自带的 18 个预设（英文名），界面用中文显示
EQ_PRESET_LABELS = {
    "Flat": "平坦",
    "Classical": "古典",
    "Club": "俱乐部",
    "Dance": "舞曲",
    "Full bass": "重低音",
    "Full bass and treble": "低高音增强",
    "Full treble": "重高音",
    "Headphones": "耳机",
    "Large Hall": "大厅",
    "Live": "现场",
    "Party": "派对",
    "Pop": "流行",
    "Reggae": "雷鬼",
    "Rock": "摇滚",
    "Ska": "斯卡",
    "Soft": "柔和",
    "Soft rock": "轻摇滚",
    "Techno": "电子",
}

_EQ_STATE_MAP = {
    vlc.State.Playing: QMediaPlayer.PlaybackState.PlayingState,
    vlc.State.Paused: QMediaPlayer.PlaybackState.PausedState,
}


class Player(QObject):
    trackChanged = Signal(object)       # Track | None
    positionChanged = Signal(int)       # ms
    durationChanged = Signal(int)       # ms
    stateChanged = Signal(object)       # QMediaPlayer.PlaybackState
    modeChanged = Signal(object)        # PlayMode
    volumeChanged = Signal(int)         # 0-100
    queueChanged = Signal()
    errorRaised = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # VLC 内核延迟到窗口显示后再创建（见 warm_up）。插件缓存未命中时，
        # libvlc 扫描插件目录可能耗时数秒，不能挡在窗口出现之前。
        self._instance = None
        self._player = None
        self._media = None
        self._pending_eq = None
        self._eq = None

        self._volume = 72
        self._muted = False
        self._output_id: bytes | None = None

        self._state = vlc.State.NothingSpecial
        self._qt_state = QMediaPlayer.PlaybackState.StoppedState
        self._last_position = -1
        self._last_duration = -1

        # 系统缺省播放设备变化时跟着切。设备插拔会触发 audioOutputsChanged，
        # 但在系统设置里单纯改默认输出不会，所以再挂一个轮询兜底。
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._follow_default_output)
        self._device_watch = QTimer(self)
        self._device_watch.setInterval(1500)
        self._device_watch.timeout.connect(self._follow_default_output)
        self._device_watch.start()

        # libVLC 没有信号回调可用（会跨线程），统一用定时器轮询状态
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(200)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self.queue: list[Track] = []
        self.index = -1
        self.mode = PlayMode.LOOP_ALL
        self._history: list[int] = []
        self._current_path = ""
        self._finished = False      # 顺序播放已经播到队列末尾
        self._error_streak = 0      # 连续失败计数，防止坏文件把队列变成死循环

        self._follow_default_output()

    # ---------------------------------------------------------------- 内核
    def _engine(self):
        """按需创建 libVLC 实例；只在首次预热或播放时发生一次。"""
        if self._player is not None:
            return self._player
        self._instance = _instance()
        self._player = self._instance.media_player_new()
        self._prepare_audio()
        pending = self._pending_eq
        if pending is not None:
            try:
                self._player.set_equalizer(pending)
            except Exception:
                pass
        return self._player

    def warm_up(self) -> None:
        """窗口显示后提前初始化内核，把等待藏在界面出现之后。"""
        self._engine()

    # ---------------------------------------------------------------- 属性
    @property
    def current_track(self) -> Track | None:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    @property
    def is_playing(self) -> bool:
        return self._state == vlc.State.Playing

    def position(self) -> int:
        if self.current_track is None:
            return 0
        return max(0, self._get_time())

    def duration(self) -> int:
        if self.current_track is None:
            return 0
        if self._last_duration > 0:
            return self._last_duration
        return max(0, self._get_length())

    # ---------------------------------------------------------------- 队列
    def play_queue(self, tracks: list[Track], start_index: int = 0) -> None:
        self.queue = [t for t in tracks if t is not None]
        if not self.queue:
            return
        self._history.clear()
        self._error_streak = 0
        self.play_index(max(0, min(start_index, len(self.queue) - 1)))

    def play_index(self, index: int, autoplay: bool = True) -> None:
        if not self.queue:
            return
        if not 0 <= index < len(self.queue):
            return
        track = self.queue[index]
        self.index = index
        self._finished = False
        self._history.append(index)
        if len(self._history) > 200:
            del self._history[:100]
        self._current_path = track.path
        self._last_position = -1
        self._last_duration = -1

        self._engine()
        self._media = self._instance.media_new(track.path)
        self._player.set_media(self._media)
        self._prepare_audio()
        self.trackChanged.emit(track)
        self.queueChanged.emit()
        if autoplay:
            self._player.play()

    def play_track(self, track: Track) -> None:
        """单独播放一首（不改变队列时使用）。"""
        self.queue = [track]
        self.play_index(0)

    def sync_queue_order(self, ordered: list[Track]) -> bool:
        """若队列与给定列表是同一批歌曲，就按新顺序重排播放队列。

        用于「拖动调整播放顺序」：界面里的顺序就是接下来的播放顺序。
        """
        if not self.queue or not ordered:
            return False
        if len(ordered) != len(self.queue):
            return False
        if {t.path for t in ordered} != {t.path for t in self.queue}:
            return False
        current = self.current_track
        if [t.path for t in ordered] == [t.path for t in self.queue]:
            return False
        self.queue = list(ordered)
        if current is not None:
            self.index = next(
                (i for i, t in enumerate(self.queue) if t.path == current.path),
                self.index,
            )
        self._history.clear()
        self.queueChanged.emit()
        return True

    def _restart_current(self) -> None:
        track = self.current_track
        if track is None:
            return
        self._engine()
        self._media = self._instance.media_new(track.path)
        self._player.set_media(self._media)
        self._prepare_audio()
        self._last_position = -1
        self._last_duration = -1
        self._player.play()

    def next(self, manual: bool = True) -> None:
        if not self.queue:
            return
        if not manual and self.mode is PlayMode.LOOP_ONE:
            self._restart_current()
            return

        if self.mode is PlayMode.SHUFFLE and len(self.queue) > 1:
            candidates = [i for i in range(len(self.queue)) if i != self.index]
            self.play_index(random.choice(candidates))
            return

        nxt = self.index + 1
        if nxt >= len(self.queue):
            if self.mode is PlayMode.SEQUENTIAL:
                self._finished = True
                if self._player is not None:
                    self._player.stop()
                return
            nxt = 0
        self.play_index(nxt)

    def previous(self) -> None:
        if not self.queue:
            return
        if self.mode is PlayMode.SHUFFLE and len(self._history) >= 2:
            self._history.pop()
            target = self._history.pop()
            self.play_index(target)
            return
        prev = self.index - 1
        if prev < 0:
            if self.mode is PlayMode.SEQUENTIAL:
                # 已是第一首：回到开头；如果当前是停着的状态，顺便重新起播
                if self._player is None:
                    self._restart_current()
                    return
                self._player.set_time(0)
                if self._live_state() in (
                    vlc.State.Stopped,
                    vlc.State.Ended,
                    vlc.State.NothingSpecial,
                ):
                    self._restart_current()
                return
            prev = len(self.queue) - 1
        self.play_index(prev)

    # ---------------------------------------------------------------- 控制
    def _live_state(self):
        """刚调用 stop/pause 后轮询还没跑，这里直接问一次 libVLC。"""
        if self._player is None:
            return self._state
        try:
            return self._player.get_state()
        except Exception:
            return self._state

    def toggle(self) -> None:
        state = self._live_state()
        if state == vlc.State.Playing:
            self._player.set_pause(1)
        elif state == vlc.State.Paused:
            self._player.play()
        elif self.current_track is not None:
            if self._finished and self.mode is PlayMode.SEQUENTIAL:
                # 整个队列播完之后按播放键，从头再来，而不是重播最后一首
                self.play_index(0)
                return
            # Stopped / Ended：从头重新加载，避免停在文件末尾
            self._restart_current()

    def pause(self) -> None:
        if self._player is not None:
            self._player.set_pause(1)

    def resume(self) -> None:
        if self._player is not None:
            self._player.play()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def seek(self, ms: int) -> None:
        if self.current_track is not None and self._player is not None:
            self._player.set_time(max(0, int(ms)))

    def seek_by(self, delta_ms: int) -> None:
        if self.current_track is None or self._player is None:
            return
        duration = max(0, self.duration())
        target = max(0, min(self.position() + delta_ms, duration - 500))
        self._player.set_time(target)

    # ---------------------------------------------------------------- 音频设备
    def _follow_default_output(self, *_args) -> None:
        """系统缺省播放设备变了就把输出切过去，播放进度和音量保持不变。"""
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            return
        ident = bytes(device.id())
        if ident == self._output_id:
            return
        self._output_id = ident
        if self.current_track is None:
            return
        self._apply_output_device()

    def _apply_output_device(self) -> None:
        """在起播前告诉 libVLC 用哪个设备，切设备不会重头播放。"""
        if not self._output_id:
            return
        if self._player is None:
            return
        try:
            self._player.audio_output_device_set(None, self._output_id)
        except Exception:
            pass

    # ---------------------------------------------------------------- 音量
    def set_volume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self._volume = value
        if self._player is not None:
            try:
                self._player.audio_set_volume(value)
            except Exception:
                pass
        self.volumeChanged.emit(value)

    def volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self._player is None:
            return
        try:
            self._player.audio_set_mute(self._muted)
        except Exception:
            pass

    # ---------------------------------------------------------------- 均衡器
    def eq_band_count(self) -> int:
        try:
            return int(vlc.libvlc_audio_equalizer_get_band_count())
        except Exception:
            return 10

    def eq_band_frequencies(self) -> list[int]:
        bands = []
        for i in range(self.eq_band_count()):
            try:
                bands.append(int(vlc.libvlc_audio_equalizer_get_band_frequency(i)))
            except Exception:
                bands.append(0)
        return bands

    def eq_preset_count(self) -> int:
        try:
            return int(vlc.libvlc_audio_equalizer_get_preset_count())
        except Exception:
            return 0

    def eq_preset_name(self, index: int) -> str:
        try:
            name = vlc.libvlc_audio_equalizer_get_preset_name(int(index))
        except Exception:
            return ""
        if isinstance(name, bytes):
            name = name.decode("utf-8", "ignore")
        return str(name or "")

    def eq_preset_label(self, index: int) -> str:
        name = self.eq_preset_name(index)
        return EQ_PRESET_LABELS.get(name, name or f"预设 {index + 1}")

    def eq_preset_gains(self, index: int) -> list[float]:
        eq = None
        try:
            eq = vlc.libvlc_audio_equalizer_new_from_preset(int(index))
            if not eq:
                return []
            return [
                float(eq.get_amp_at_index(i)) for i in range(self.eq_band_count())
            ]
        except Exception:
            return []
        finally:
            if eq is not None:
                try:
                    eq.release()
                except Exception:
                    pass

    def apply_eq_preset(self, index: int) -> bool:
        eq = None
        try:
            eq = vlc.libvlc_audio_equalizer_new_from_preset(int(index))
            if not eq:
                return False
            self._replace_eq(eq)
            return True
        except Exception:
            if eq is not None:
                try:
                    eq.release()
                except Exception:
                    pass
            return False

    def apply_eq_custom(self, gains: list[float], preamp: float = 0.0) -> bool:
        eq = None
        try:
            eq = vlc.AudioEqualizer()
            if not eq:
                return False
            eq.set_preamp(max(-20.0, min(20.0, float(preamp))))
            for i, gain in enumerate(gains[: self.eq_band_count()]):
                eq.set_amp_at_index(max(-20.0, min(20.0, float(gain))), i)
            self._replace_eq(eq)
            return True
        except Exception:
            if eq is not None:
                try:
                    eq.release()
                except Exception:
                    pass
            return False

    def disable_eq(self) -> None:
        self._pending_eq = None
        if self._player is not None:
            try:
                self._player.set_equalizer(None)
            except Exception:
                pass
        self._release_eq()

    def _replace_eq(self, eq) -> None:
        previous = self._eq
        # libVLC 不持有引用，必须自己留在对象上，否则会被回收导致无声
        self._eq = eq
        self._pending_eq = eq
        if self._player is not None:
            try:
                self._player.set_equalizer(eq)
            except Exception:
                pass
        if previous is not None and previous is not eq:
            try:
                previous.release()
            except Exception:
                pass

    def _release_eq(self) -> None:
        eq = self._eq
        self._eq = None
        if eq is not None:
            try:
                eq.release()
            except Exception:
                pass

    # ---------------------------------------------------------------- 模式
    def set_mode(self, mode: PlayMode) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        self.modeChanged.emit(mode)

    def cycle_mode(self) -> None:
        index = MODE_ORDER.index(self.mode)
        self.set_mode(MODE_ORDER[(index + 1) % len(MODE_ORDER)])

    # ---------------------------------------------------------------- 内部
    def _prepare_audio(self) -> None:
        """起播前把音量、静音和设备都交代给 libVLC。"""
        if self._player is None:
            return
        self._apply_output_device()
        try:
            self._player.audio_set_mute(self._muted)
            self._player.audio_set_volume(self._volume)
        except Exception:
            pass

    def _get_time(self) -> int:
        if self._player is None:
            return -1
        try:
            return int(self._player.get_time())
        except Exception:
            return -1

    def _get_length(self) -> int:
        if self._player is None:
            return -1
        try:
            return int(self._player.get_length())
        except Exception:
            return -1

    def _tick(self) -> None:
        if self._player is None:
            return
        try:
            state = self._player.get_state()
        except Exception:
            return
        if state != self._state:
            self._state = state
            self._on_vlc_state(state)

        if self.current_track is None:
            return

        position = self._get_time()
        if position >= 0 and position != self._last_position:
            self._last_position = position
            self.positionChanged.emit(position)

        length = self._get_length()
        if length > 0 and length != self._last_duration:
            self._last_duration = length
            self.durationChanged.emit(length)

    def _on_vlc_state(self, state) -> None:
        mapped = _EQ_STATE_MAP.get(state, QMediaPlayer.PlaybackState.StoppedState)
        if mapped != self._qt_state:
            self._qt_state = mapped
            self.stateChanged.emit(mapped)

        if state == vlc.State.Playing:
            self._error_streak = 0
            # 新的音频输出刚建好，把音量和静音再压一次（VLC 起播时可能回到默认 100%）
            try:
                self._player.audio_set_mute(self._muted)
                self._player.audio_set_volume(self._volume)
            except Exception:
                pass
        elif state == vlc.State.Ended:
            if self.mode is PlayMode.LOOP_ONE:
                self._restart_current()
            else:
                self.next(manual=False)
        elif state == vlc.State.Error:
            self._on_error()

    def _on_error(self) -> None:
        name = self.current_track.title if self.current_track else "该文件"
        message = ""
        try:
            raw = vlc.libvlc_errmsg()
            if raw:
                message = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
        except Exception:
            message = ""
        self.errorRaised.emit(f"无法播放《{name}》：{message or '文件已损坏或格式不受支持'}")

        # 单个文件坏掉不该把整个队列卡住：自动跳到下一首。
        # 但整队列都失败时要停下，否则会无限循环；单曲循环同理。
        limit = max(0, len(self.queue) - 1)
        if self.mode is PlayMode.LOOP_ONE or self._error_streak >= limit:
            self._error_streak = 0
            self._player.stop()
            return
        self._error_streak += 1
        self.next(manual=False)
