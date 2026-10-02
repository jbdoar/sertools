"""SerialDevice.query against a device whose answers arrive after a delay."""

from __future__ import annotations

import time

import pytest

from sertools import SerialDevice


class DelayedDevice:
    """A pyserial stand-in that answers commands one at a time, like a real
    device: each answer becomes readable `delay` seconds after the previous
    one (or after its command, if the device was idle)."""

    def __init__(self, answers: dict[str, bytes], delay: float = 0.05):
        self.answers = answers
        self.delay = delay
        self.pending: list[tuple[float, bytes]] = []
        self.written = b""

    def write(self, data: bytes) -> int:
        self.written += data
        while b"\r" in self.written:
            command, _, self.written = self.written.partition(b"\r")
            answer = self.answers.get(command.decode(), b"\r\nOk\r\n")
            last = self.pending[-1][0] if self.pending else 0.0
            self.pending.append((max(time.monotonic(), last) + self.delay, answer))
        return len(data)

    def _ready(self) -> bytes:
        now = time.monotonic()
        ready = b"".join(data for at, data in self.pending if at <= now)
        self.pending = [(at, data) for at, data in self.pending if at > now]
        return ready

    @property
    def in_waiting(self) -> int:
        self._buffer = getattr(self, "_buffer", b"") + self._ready()
        return len(self._buffer)

    def read(self, size: int = 1) -> bytes:
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def reset_input_buffer(self) -> None:
        self._ready()  # only what has already arrived is discarded
        self._buffer = b""

    def reset_output_buffer(self) -> None:
        pass


def make_device(answers, **kwargs):
    device = SerialDevice(port=None, timeout=None, newline_tx="\r", newline_rx="\r\n",
                          terminator="Ok", terminator_cmd="\r")
    device.ser = DelayedDevice(answers, **kwargs)
    return device


ANSWERS = {
    # A one-line answer, read with num_lines=1; the device's Ok for the
    # injected terminator_cmd follows (as its own answer) a moment later.
    "tgr": b"\r\nd1_gain:1,2,3\r\n",
    "cpa": b"\r\n1,+0\r\n2,+0\r\n3,+0\r\n",
}


def test_num_lines_read_consumes_the_late_acknowledgment():
    device = make_device(ANSWERS)
    assert device.query("tgr", num_lines=1) == "d1_gain:1,2,3"
    # Without draining, tgr's late 'Ok' would end this response immediately.
    assert device.query("cpa") == ["1,+0", "2,+0", "3,+0"]


def test_draining_waits_no_longer_than_drain_timeout():
    # A device that never acknowledges the terminator command.
    device = make_device({**ANSWERS, "": b""})
    start = time.monotonic()
    assert device.query("tgr", num_lines=1, drain_timeout=0.2) == "d1_gain:1,2,3"
    assert time.monotonic() - start == pytest.approx(0.25, abs=0.15)


def test_no_draining_when_the_terminator_was_already_read():
    device = make_device({"one": b"\r\nOk\r\n"})
    start = time.monotonic()
    device.query("one", num_lines=1)
    assert time.monotonic() - start < 0.2
