from __future__ import annotations

import socket
from dataclasses import dataclass


class TcpClientError(RuntimeError):
    pass


@dataclass
class TcpEndpoint:
    host: str
    port: int


class TcpClient:
    def __init__(self, endpoint: TcpEndpoint, connect_timeout: float, recv_timeout: float) -> None:
        self.endpoint = endpoint
        self.connect_timeout = connect_timeout
        self.recv_timeout = recv_timeout
        self._sock: socket.socket | None = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout)
        try:
            sock.connect((self.endpoint.host, self.endpoint.port))
            sock.settimeout(self.recv_timeout)
            self._sock = sock
        except OSError as exc:
            sock.close()
            raise TcpClientError(
                f"连接失败: {self.endpoint.host}:{self.endpoint.port}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            finally:
                self._sock = None

    def send_all(self, data: bytes) -> None:
        if self._sock is None:
            raise TcpClientError("socket 未连接")
        try:
            self._sock.sendall(data)
        except OSError as exc:
            self.close()
            raise TcpClientError(f"发送失败: {exc}") from exc

    def recv_some(self, max_bytes: int = 4096) -> bytes:
        if self._sock is None:
            raise TcpClientError("socket 未连接")
        try:
            data = self._sock.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as exc:
            self.close()
            raise TcpClientError(f"接收失败: {exc}") from exc
        if data == b"":
            self.close()
            raise TcpClientError("连接已关闭")
        return data
