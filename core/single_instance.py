"""单实例保护：再次启动时唤起已有窗口，而不是开出第二个播放器。

两个 Lumen 同时跑会各自写一份 library.json、各装一个键盘钩子，
媒体键还会互相触发，所以启动时先抢一个本地 socket 名字。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

INSTANCE_KEY = "LumenAudio.Lumen.SingleInstance"


class SingleInstance(QObject):
    """acquire() 为 True 时本进程是唯一实例；否则已有实例会被唤起。"""

    activated = Signal()
    open_requested = Signal(list)  # 第二实例带来的音频文件/文件夹路径

    def __init__(self, key: str = INSTANCE_KEY, parent=None):
        super().__init__(parent)
        self._key = key
        self._server: QLocalServer | None = None

    def acquire(self, paths: list[str] | None = None, timeout_ms: int = 400) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self._key)
        if probe.waitForConnected(timeout_ms):
            # 已有实例在跑：让它显示窗口并打开带来的文件，然后自己退出。
            probe.write(b"show\n")
            for path in paths or []:
                probe.write(f"open\t{path}\n".encode("utf-8"))
            probe.flush()
            # Qt6 的管道写入由事件循环驱动，阻塞式 waitForBytesWritten 不生效，
            # 必须泵事件让数据真正写进管道，再立即关闭（数据已进服务端缓冲）。
            deadline = time.monotonic() + timeout_ms / 1000 + 0.2
            while probe.bytesToWrite() > 0 and time.monotonic() < deadline:
                QCoreApplication.processEvents(
                    QEventLoop.ProcessEventsFlag.AllEvents, 20
                )
            probe.abort()
            return False

        # 上一次可能是崩溃退出，留下了一个连不上的名字，先清掉。
        QLocalServer.removeServer(self._key)
        server = QLocalServer(self)
        if not server.listen(self._key):
            # 监听失败（权限/沙箱等）也照常启动，别因为单实例机制打不开程序。
            return True
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
            QLocalServer.removeServer(self._key)

    def _on_connection(self) -> None:
        server = self._server
        if server is None:
            return
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            if connection is None:
                break
            # 数据在 disconnected 时保证收齐，统一在那里解析
            connection.disconnected.connect(
                lambda sock=connection: self._handle_connection(sock)
            )
            if connection.state() == QLocalSocket.ConnectionState.UnconnectedState:
                # 客户端连上即断开的极端情况，disconnected 可能已经发过
                self._handle_connection(connection)

    def _handle_connection(self, connection) -> None:
        data = bytes(connection.readAll())
        connection.deleteLater()

        paths: list[str] = []
        saw_show = False
        for line in data.decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if line == "show":
                saw_show = True
            elif line.startswith("open\t"):
                path = line[5:].strip()
                if path:
                    paths.append(path)
        if saw_show:
            self.activated.emit()
        if paths:
            self.open_requested.emit(paths)
