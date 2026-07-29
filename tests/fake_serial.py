from __future__ import annotations

from collections import deque
from threading import Condition
from time import monotonic


class MemorySerial:
    """One endpoint of an in-memory, bidirectional serial connection."""

    def __init__(self, *, timeout: float | None = 1.0):
        self.timeout = timeout
        self._rx = deque()
        self._condition = Condition()
        self._peer: MemorySerial | None = None
        self.is_open = True

    def connect(self, peer: "MemorySerial") -> None:
        self._peer = peer

    @property
    def in_waiting(self) -> int:
        with self._condition:
            return len(self._rx)

    def write(self, data: bytes | bytearray | memoryview) -> int:
        if not self.is_open:
            raise OSError("Serial port is closed")

        if self._peer is None:
            raise RuntimeError("Serial endpoint is not connected")

        payload = bytes(data)

        with self._peer._condition:
            self._peer._rx.extend(payload)
            self._peer._condition.notify_all()

        return len(payload)

    def read(self, size: int = 1) -> bytes:
        if size <= 0:
            return b""

        if not self.is_open:
            raise OSError("Serial port is closed")

        deadline = (
            None
            if self.timeout is None
            else monotonic() + self.timeout
        )

        result = bytearray()

        with self._condition:
            while len(result) < size:
                while not self._rx:
                    if deadline is None:
                        self._condition.wait()
                        continue

                    remaining = deadline - monotonic()

                    if remaining <= 0:
                        return bytes(result)

                    self._condition.wait(timeout=remaining)

                while self._rx and len(result) < size:
                    result.append(self._rx.popleft())

        return bytes(result)

    def flush(self) -> None:
        """Writes are immediate, so there is nothing to flush."""

    def reset_input_buffer(self) -> None:
        with self._condition:
            self._rx.clear()

    def close(self) -> None:
        with self._condition:
            self.is_open = False
            self._condition.notify_all()


def memory_serial_pair(
    *,
    timeout: float | None = 1.0,
) -> tuple[MemorySerial, MemorySerial]:
    left = MemorySerial(timeout=timeout)
    right = MemorySerial(timeout=timeout)

    left.connect(right)
    right.connect(left)

    return left, right
