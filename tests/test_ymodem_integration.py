from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sertools.ymodem import YModemReceiver, YModemSender

from .fake_serial import memory_serial_pair


def test_ymodem_sender_receiver_round_trip(tmp_path: Path):
    source = tmp_path / "source.bin"
    output_dir = tmp_path / "received"
    output_dir.mkdir()

    original_data = bytes(range(256)) * 20 + b"final partial block"
    source.write_bytes(original_data)

    sender_serial, receiver_serial = memory_serial_pair(timeout=0.25)

    sender = YModemSender(sender_serial)
    receiver = YModemReceiver(receiver_serial)

    with ThreadPoolExecutor(max_workers=2) as executor:
        receiver_future = executor.submit(
            receiver.receive,
            output_dir,
        )

        sender_future = executor.submit(
            sender.send,
            source,
        )

        sender_result = sender_future.result(timeout=10)
        received_paths = receiver_future.result(timeout=10)

    assert sender_result is not False
    assert len(received_paths) == 1

    received_path = received_paths[0]

    assert received_path.name == source.name
    assert received_path.read_bytes() == original_data
