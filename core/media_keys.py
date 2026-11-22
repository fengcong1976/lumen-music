"""全局媒体键：Windows 下用低级键盘钩子监听，其他平台自动跳过。

优先注册系统热键（更轻量）；若媒体键已被别的程序占用，则退回到
WH_KEYBOARD_LL 低级键盘钩子——它只观察、不拦截，因此即使系统里
已经有别的播放器响应，Lumen 也能拿到按键事件。

注册成功后，即使窗口没有焦点（甚至隐藏在托盘里），键盘上的
播放/暂停、上一首、下一首、停止键也能控制播放器。
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QCoreApplication,
    QObject,
    Qt,
    Signal,
)

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WH_KEYBOARD_LL = 13
MOD_NOREPEAT = 0x4000

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# 热键 id -> 虚拟键码
_HOTKEYS = {
    1: VK_MEDIA_PLAY_PAUSE,
    2: VK_MEDIA_NEXT_TRACK,
    3: VK_MEDIA_PREV_TRACK,
    4: VK_MEDIA_STOP,
}
_VK_TO_ID = {vk: hotkey_id for hotkey_id, vk in _HOTKEYS.items()}

_KBDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint32),
        ("scanCode", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MediaKeyWatcher(QObject):
    """把系统级媒体键转成 Qt 信号。"""

    playPause = Signal()
    nextPressed = Signal()
    previousPressed = Signal()
    stopPressed = Signal()

    # 内部信号：键盘钩子/原生事件里只负责 emit，真正干活排到事件循环里。
    # 低级键盘钩子的回调有 300ms 超时，超时 Windows 会静默摘钩；
    # 在回调里直接操作播放器（读文件、换 source）很容易踩线。
    _keyQueued = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._method = ""
        self._hook = None
        self._proc = None
        self._registered: list[int] = []
        self._hook_ids: set[int] = set()
        self._hotkey_filter = None
        self._keyQueued.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    # ---------------------------------------------------------------- 属性
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def method(self) -> str:
        """当前生效的方式：hotkey / hook / 空字符串。"""
        return self._method

    @property
    def platforms_supported(self) -> bool:
        return sys.platform.startswith("win")

    def describe(self) -> str:
        if not self.platforms_supported:
            return "当前系统不支持全局媒体键"
        if self._method == "hotkey":
            return "已注册系统媒体热键"
        if self._method == "hotkey+hook":
            return "媒体键部分被占用：热键 + 键盘钩子"
        if self._method == "hook":
            return "已启用键盘钩子监听媒体键"
        return "媒体键不可用（可能被其他程序占用）"

    # ---------------------------------------------------------------- 启停
    def start(self) -> bool:
        if self._enabled or not self.platforms_supported:
            return False
        self._start_hotkeys()
        remaining = set(_HOTKEYS) - set(self._registered)
        if not remaining:
            self._method = "hotkey"
            self._enabled = True
            return True
        # 有键被别的程序占了：热键留着，剩下的交给键盘钩子补上，
        # 不能让「注册上 2 个」变成「另外 2 个彻底不响应」。
        self._hook_ids = remaining
        if self._start_hook():
            self._method = "hotkey+hook" if self._registered else "hook"
            self._enabled = True
            return True
        self._hook_ids = set()
        if self._registered:
            self._method = "hotkey"
            self._enabled = True
            return True
        return False

    def stop(self) -> None:
        if not self._enabled:
            return
        # 两种方式可能同时生效（部分热键 + 钩子兜底），一律清干净。
        self._stop_hook()
        self._stop_hotkeys()
        self._hook_ids = set()
        self._method = ""
        self._enabled = False

    # ---------------------------------------------------------------- 热键
    def _user32(self):
        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint
        ]
        user32.RegisterHotKey.restype = ctypes.c_int
        user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.UnregisterHotKey.restype = ctypes.c_int
        return user32

    def _start_hotkeys(self) -> bool:
        """能注册几个注册几个，返回是否全部注册成功。"""
        try:
            user32 = self._user32()
        except (AttributeError, OSError):
            return False
        app = _app_instance()
        if app is None:
            return False
        for hotkey_id, vk in _HOTKEYS.items():
            if user32.RegisterHotKey(None, hotkey_id, MOD_NOREPEAT, vk):
                self._registered.append(hotkey_id)
        if not self._registered:
            return False
        if self._hotkey_filter is None:
            self._hotkey_filter = _NativeFilter(self)
            app.installNativeEventFilter(self._hotkey_filter)
        return len(self._registered) == len(_HOTKEYS)

    def _stop_hotkeys(self) -> None:
        app = _app_instance()
        if app is not None and getattr(self, "_hotkey_filter", None) is not None:
            app.removeNativeEventFilter(self._hotkey_filter)
        self._hotkey_filter = None
        try:
            user32 = self._user32()
            for hotkey_id in self._registered:
                user32.UnregisterHotKey(None, hotkey_id)
        except (AttributeError, OSError):
            pass
        self._registered.clear()

    # ---------------------------------------------------------------- 钩子
    def _start_hook(self) -> bool:
        if not self._hook_ids:
            return False
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
        except (AttributeError, OSError):
            return False

        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, _KBDPROC, ctypes.c_void_p, ctypes.c_uint
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = ctypes.c_int
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        def callback(code, wparam, lparam):
            try:
                if code >= 0 and wparam in (WM_KEYUP, WM_SYSKEYUP):
                    info = _KBDLLHOOKSTRUCT.from_address(int(lparam))
                    hotkey_id = _VK_TO_ID.get(int(info.vkCode))
                    if hotkey_id is not None and hotkey_id in self._hook_ids:
                        # 只 emit，不在钩子回调里做实际工作
                        self._keyQueued.emit(hotkey_id)
            except Exception:
                pass
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._proc = _KBDPROC(callback)   # 必须持有引用，否则会被回收
        handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0
        )
        if not handle:
            self._proc = None
            return False
        self._hook = handle
        return True

    def _stop_hook(self) -> None:
        if self._hook:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(self._hook)
            except (AttributeError, OSError):
                pass
            self._hook = None
        self._proc = None

    # ---------------------------------------------------------------- 派发
    def _dispatch(self, hotkey_id: int) -> None:
        signals = {
            1: self.playPause,
            2: self.nextPressed,
            3: self.previousPressed,
            4: self.stopPressed,
        }
        signal = signals.get(hotkey_id)
        if signal is not None:
            signal.emit()


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint32),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
    ]


class _NativeFilter(QAbstractNativeEventFilter):
    """热键方式下，从线程消息里捞 WM_HOTKEY。"""

    def __init__(self, watcher: "MediaKeyWatcher"):
        super().__init__()
        self._watcher = watcher

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            name = bytes(event_type)
        except (TypeError, ValueError):
            name = event_type
        if name != b"windows_generic_MSG":
            return False
        try:
            msg = _Msg.from_address(int(message))
        except (TypeError, ValueError):
            return False
        if msg.message == 0x0312:  # WM_HOTKEY
            self._watcher._keyQueued.emit(int(msg.wParam))
            return True
        return False


def _app_instance():
    return QCoreApplication.instance()
