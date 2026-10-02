"""SerialDevice.query against a device whose answers arrive after a delay."""

from __future__ import annotations

import time

import pytest

from sertools import QueryTimeout, SerialDevice


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


def test_timeout_returns_the_partial_response_by_default():
    # A device that stalls mid-response and never acknowledges.
    device = make_device({"osp": b"\r\n1,2,3\r\n4,5", "": b""})
    assert device.query("osp", timeout=0.2) == ["1,2,3", "4,5"]


def test_raise_on_timeout_raises_with_what_arrived():
    device = make_device({"osp": b"\r\n1,2,3\r\n4,5", "": b""})
    with pytest.raises(QueryTimeout) as info:
        device.query("osp", timeout=0.2, raise_on_timeout=True)
    assert isinstance(info.value, TimeoutError)
    assert info.value.command == "osp" and info.value.response == ["1,2,3", "4,5"]


def test_raise_on_timeout_discards_the_late_rest_of_the_response():
    # The answer arrives after the query has given up; it must not be taken
    # as the next query's response.
    device = make_device({"slow": b"\r\nlate\r\nOk\r\n"}, delay=0.3)
    with pytest.raises(QueryTimeout):
        device.query("slow", timeout=0.1, raise_on_timeout=True)
    assert device.query("next") == []


def test_no_raise_when_the_response_completes_in_time():
    device = make_device({"cpa": b"\r\n1,+0\r\nOk\r\n"})
    assert device.query("cpa", timeout=1.0, raise_on_timeout=True) == "1,+0"


class HoldingDevice(DelayedDevice):
    """Sends only part of a response and holds the rest until it next
    receives something (seen on an RS-9 answering SCP)."""

    def __init__(self, answers, held: bytes, **kwargs):
        super().__init__(answers, **kwargs)
        self.held = held
        self.written_any = False

    def write(self, data: bytes) -> int:
        # Once the partial response is out, anything received releases the
        # rest, ahead of its own answer.
        if self.held and self.pending == [] and self.written_any:
            self.pending.append((time.monotonic(), self.held))
            self.held = b""
        self.written_any = True
        return super().write(data)


def test_a_held_back_rest_of_a_response_is_released_and_discarded():
    device = make_device({})
    device.ser = HoldingDevice({"scp": b"\r\n1,0.5\r\n28,0.97", "": b""},
                               held=b"2213\r\n30,0.04\r\nOk\r\n")
    with pytest.raises(QueryTimeout) as info:
        device.query("scp", timeout=0.2, raise_on_timeout=True)
    assert info.value.response == ["1,0.5", "28,0.97"]
    device.ser.answers["pre12"] = b"\r\n12,Blue\r\nOk\r\n"
    assert device.query("pre12") == "12,Blue"


def test_idle_timeout_without_terminator_cmd_sends_only_the_command():
    # A long-running measurement: progress lines, then a quiet device. Only
    # the command itself may reach it.
    device = make_device({"mpc5": b"\r\nphase 1\r\nphase 2\r\nOk\r\n"})
    sent = []
    write = device.ser.write
    device.ser.write = lambda data: sent.append(data) or write(data)
    start = time.monotonic()
    lines = device.query("mpc5", terminator=None, terminator_cmd=None,
                         terminator_idle_timeout=0.3, timeout=5.0, raise_on_timeout=True)
    assert lines == ["phase 1", "phase 2", "Ok"]
    assert time.monotonic() - start == pytest.approx(0.35, abs=0.15)
    assert sent == [b"mpc5\r"]


def test_idle_timeout_without_terminator_cmd_covers_a_silent_device():
    device = make_device({"blvs": b""})
    start = time.monotonic()
    assert device.query("blvs", terminator=None, terminator_cmd=None,
                        terminator_idle_timeout=0.3, timeout=5.0, raise_on_timeout=True) == []
    assert time.monotonic() - start < 0.6
