from __future__ import annotations

from enum import Enum, auto


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    CONFIGURING = auto()
    ACQUIRING = auto()
    RECONNECT_WAIT = auto()
    STOPPING = auto()
    ERROR = auto()
