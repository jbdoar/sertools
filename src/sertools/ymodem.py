# src/sertools/ymodem.py

"""
Send and receive files using YMODEM.

The sender and receiver operate on a pySerial-compatible transport with:

    read(size) -> bytes
    write(data) -> int | None
    flush()
    timeout

The module supports CRC-mode YMODEM with 128-byte and 1024-byte data
packets.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


# Protocol control characters
SOH = 0x01
STX = 0x02
EOT = 0x04
ACK = 0x06
NAK = 0x15
CAN = 0x18

CRC_REQUEST = ord("C")

# CP/M end-of-file byte traditionally used to pad the last data block.
CPMEOF = 0x1A

HEADER_BLOCK_SIZE = 128
DEFAULT_DATA_BLOCK_SIZE = 1024


class YModemError(Exception):
    """
    Base class for YMODEM errors.
    """


class YModemTimeout(YModemError):
    """
    Raised when a protocol operation times out.
    """


class YModemCancelled(YModemError):
    """
    Raised when the remote endpoint cancels the transfer.
    """


class YModemRetriesExceeded(YModemError):
    """
    Raised when a protocol operation exceeds its retry limit.
    """


class YModemProtocolError(YModemError):
    """
    Raised when invalid protocol data is received.
    """


@dataclass(frozen=True)
class YModemPacket:
    """
    Parsed YMODEM packet.
    """

    block_number: int
    payload: bytes


@dataclass(frozen=True)
class YModemFileHeader:
    """
    Metadata extracted from a YMODEM block-zero packet.
    """

    filename: str
    file_size: int | None


def crc16_xmodem(data: bytes) -> int:
    """
    Calculate CRC-16/XMODEM.

    Polynomial:
        0x1021

    Initial value:
        0x0000
    """
    crc = 0

    for byte in data:
        crc ^= byte << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


def pad_block(
        data: bytes,
        size: int,
        *,
        padding: int = CPMEOF,
) -> bytes:
    """
    Pad data to exactly size bytes.
    """
    if size not in (128, 1024):
        raise ValueError(
            "block size must be either 128 or 1024"
        )

    if not 0 <= padding <= 0xFF:
        raise ValueError(
            "padding must be an integer from 0 to 255"
        )

    if len(data) > size:
        raise ValueError(
            f"data contains {len(data)} bytes; "
            f"block size is only {size}"
        )

    return data + bytes([padding]) * (size - len(data))


def make_packet(
        block_number: int,
        payload: bytes,
) -> bytes:
    """
    Construct a CRC-mode XMODEM/YMODEM packet.

    Packet structure:

        SOH/STX
        block number
        one's-complement block number
        payload
        two-byte big-endian CRC
    """
    if len(payload) == 128:
        start = SOH
    elif len(payload) == 1024:
        start = STX
    else:
        raise ValueError(
            "payload must contain exactly 128 or 1024 bytes"
        )

    block_number &= 0xFF
    complement = 0xFF - block_number

    crc = crc16_xmodem(payload)

    return (
        bytes([
            start,
            block_number,
            complement,
        ])
        + payload
        + crc.to_bytes(2, byteorder="big")
    )


def parse_packet(
        start: int,
        body: bytes,
) -> YModemPacket:
    """
    Parse and validate a packet after its SOH or STX byte.

    body must contain:

        block number
        complement
        payload
        CRC high byte
        CRC low byte
    """
    if start == SOH:
        payload_size = 128
    elif start == STX:
        payload_size = 1024
    else:
        raise YModemProtocolError(
            f"invalid packet start byte: 0x{start:02x}"
        )

    expected_length = 2 + payload_size + 2

    if len(body) != expected_length:
        raise YModemProtocolError(
            f"packet body contains {len(body)} bytes; "
            f"expected {expected_length}"
        )

    block_number = body[0]
    complement = body[1]

    if complement != (0xFF - block_number):
        raise YModemProtocolError(
            "invalid block-number complement"
        )

    payload = body[2:2 + payload_size]

    received_crc = int.from_bytes(
        body[-2:],
        byteorder="big",
    )
    calculated_crc = crc16_xmodem(payload)

    if received_crc != calculated_crc:
        raise YModemProtocolError(
            f"packet CRC mismatch: "
            f"received 0x{received_crc:04x}, "
            f"calculated 0x{calculated_crc:04x}"
        )

    return YModemPacket(
        block_number=block_number,
        payload=payload,
    )


def make_header_payload(
        filename: str,
        file_size: int,
) -> bytes:
    """
    Construct a 128-byte YMODEM block-zero payload.

    The emitted metadata is:

        filename NUL decimal-filesize NUL
    """
    if not filename:
        raise ValueError("filename cannot be empty")

    if file_size < 0:
        raise ValueError("file size cannot be negative")

    try:
        filename_bytes = filename.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "YMODEM filename must contain ASCII characters"
        ) from exc

    size_bytes = str(file_size).encode("ascii")

    metadata = (
        filename_bytes
        + b"\0"
        + size_bytes
        + b"\0"
    )

    if len(metadata) > HEADER_BLOCK_SIZE:
        raise ValueError(
            "filename and file-size metadata do not fit "
            "in a 128-byte YMODEM header"
        )

    return metadata.ljust(
        HEADER_BLOCK_SIZE,
        b"\0",
    )


def make_empty_header_payload() -> bytes:
    """
    Construct the empty block-zero payload that ends a batch.
    """
    return bytes(HEADER_BLOCK_SIZE)


def parse_header_payload(
        payload: bytes,
) -> YModemFileHeader | None:
    """
    Parse a YMODEM block-zero payload.

    Returns None for the empty block zero that terminates a batch.
    """
    if len(payload) != HEADER_BLOCK_SIZE:
        raise YModemProtocolError(
            "header payload must contain exactly 128 bytes"
        )

    fields = payload.split(b"\0")
    filename_bytes = fields[0]

    if not filename_bytes:
        return None

    try:
        filename = filename_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise YModemProtocolError(
            "received filename is not valid ASCII"
        ) from exc

    file_size = None

    if len(fields) > 1 and fields[1]:
        # The YMODEM header may contain optional metadata after the
        # decimal file size, separated by spaces.
        size_field = fields[1].split(maxsplit=1)[0]

        try:
            file_size = int(size_field)
        except ValueError as exc:
            raise YModemProtocolError(
                f"invalid file size in header: {fields[1]!r}"
            ) from exc

        if file_size < 0:
            raise YModemProtocolError(
                "received file size cannot be negative"
            )

    return YModemFileHeader(
        filename=filename,
        file_size=file_size,
    )


def iter_file_blocks(
        file: BinaryIO,
        block_size: int,
) -> Iterator[bytes]:
    """
    Yield padded data blocks from an open binary file.
    """
    if block_size not in (128, 1024):
        raise ValueError(
            "block size must be either 128 or 1024"
        )

    while True:
        data = file.read(block_size)

        if not data:
            return

        yield pad_block(
            data,
            block_size,
            padding=CPMEOF,
        )


class _YModemTransport:
    """
    Shared timeout-aware transport operations.
    """

    def __init__(
            self,
            transport,
            *,
            timeout: float,
            retries: int,
    ):
        if timeout <= 0:
            raise ValueError(
                "timeout must be greater than zero"
            )

        if retries <= 0:
            raise ValueError(
                "retries must be greater than zero"
            )

        self.transport = transport
        self.timeout = timeout
        self.retries = retries

    def _read_exact(
            self,
            size: int,
            *,
            timeout: float | None = None,
    ) -> bytes:
        """
        Read exactly size bytes or raise YModemTimeout.
        """
        if size < 0:
            raise ValueError(
                "size cannot be negative"
            )

        deadline = time.monotonic() + (
            self.timeout
            if timeout is None
            else timeout
        )

        data = bytearray()

        while len(data) < size:
            remaining_time = (
                deadline - time.monotonic()
            )

            if remaining_time <= 0:
                raise YModemTimeout(
                    f"timed out after receiving "
                    f"{len(data)}/{size} bytes"
                )

            chunk = self._read_some(
                size - len(data),
                timeout=remaining_time,
            )

            if not chunk:
                continue

            data.extend(chunk)

        return bytes(data)

    def _read_byte(
            self,
            *,
            timeout: float | None = None,
    ) -> int | None:
        """
        Read one byte.

        Returns None when no byte arrives before the timeout.
        """
        data = self._read_some(
            1,
            timeout=timeout,
        )

        if not data:
            return None

        return data[0]

    def _read_some(
            self,
            size: int,
            *,
            timeout: float | None = None,
    ) -> bytes:
        """
        Perform one timeout-aware transport read.
        """
        previous_timeout = getattr(
            self.transport,
            "timeout",
            None,
        )

        if timeout is not None:
            self.transport.timeout = max(
                0.0,
                timeout,
            )

        try:
            return self.transport.read(size)
        finally:
            if timeout is not None:
                self.transport.timeout = previous_timeout

    def _write_all(
            self,
            data: bytes,
    ):
        """
        Write all bytes, handling partial writes.
        """
        offset = 0

        while offset < len(data):
            written = self.transport.write(
                data[offset:]
            )

            if written is None:
                # Some file-like transports return None after accepting
                # the complete write.
                written = len(data) - offset

            if written <= 0:
                raise YModemTimeout(
                    "transport accepted no data"
                )

            offset += written

        self.transport.flush()

    def _write_control(
            self,
            value: int,
    ):
        self._write_all(bytes([value]))

    def _read_packet_after_start(
            self,
            start: int,
    ) -> YModemPacket:
        if start == SOH:
            payload_size = 128
        elif start == STX:
            payload_size = 1024
        else:
            raise YModemProtocolError(
                f"invalid packet start byte: "
                f"0x{start:02x}"
            )

        body = self._read_exact(
            2 + payload_size + 2
        )

        return parse_packet(
            start,
            body,
        )

    def _cancel_quietly(self):
        """
        Attempt to cancel the transfer without masking another error.
        """
        try:
            self._write_all(
                bytes([CAN, CAN])
            )
        except Exception:
            pass


class YModemSender(_YModemTransport):
    """
    Send one file as a complete YMODEM batch.

    Although one file is sent per call, the sender emits the final empty
    block-zero packet required to terminate the YMODEM batch.
    """

    def __init__(
            self,
            transport,
            *,
            timeout: float = 10.0,
            retries: int = 10,
            block_size: int = DEFAULT_DATA_BLOCK_SIZE,
            startup_timeout: float | None = None,
            progress: Callable[
                [int, int],
                None,
            ] | None = None,
    ):
        super().__init__(
            transport,
            timeout=timeout,
            retries=retries,
        )

        if block_size not in (128, 1024):
            raise ValueError(
                "block_size must be either 128 or 1024"
            )

        if (
                startup_timeout is not None
                and startup_timeout <= 0
        ):
            raise ValueError(
                "startup_timeout must be greater than zero"
            )

        self.block_size = block_size
        self.startup_timeout = (
            timeout
            if startup_timeout is None
            else startup_timeout
        )
        self.progress = progress

    def send(
            self,
            path,
            *,
            transmitted_name: str | None = None,
    ) -> int:
        """
        Send one file and terminate the YMODEM batch.

        Returns the original file size.
        """
        path = Path(path)

        if not path.is_file():
            raise FileNotFoundError(path)

        file_size = path.stat().st_size
        filename = transmitted_name or path.name

        # Validate the header before interacting with the receiver.
        make_header_payload(
            filename,
            file_size,
        )

        previous_timeout = getattr(
            self.transport,
            "timeout",
            None,
        )

        started = False

        try:
            self.transport.timeout = self.timeout

            self._wait_for_crc_request(
                timeout=self.startup_timeout,
            )
            started = True

            self._send_file_header(
                filename=filename,
                file_size=file_size,
            )

            self._wait_for_crc_request()

            with path.open("rb") as file:
                self._send_file_data(
                    file,
                    file_size=file_size,
                )

            self._finish_file()

            self._wait_for_crc_request()
            self._send_batch_end()

            return file_size

        except Exception:
            if started:
                self._cancel_quietly()

            raise

        finally:
            self.transport.timeout = previous_timeout

    def _send_file_header(
            self,
            *,
            filename: str,
            file_size: int,
    ):
        payload = make_header_payload(
            filename,
            file_size,
        )

        self._send_packet(
            make_packet(0, payload)
        )

    def _send_file_data(
            self,
            file: BinaryIO,
            *,
            file_size: int,
    ):
        block_number = 1
        sent = 0

        for payload in iter_file_blocks(
                file,
                self.block_size,
        ):
            packet = make_packet(
                block_number,
                payload,
            )

            self._send_packet(packet)

            sent = min(
                sent + self.block_size,
                file_size,
            )

            if self.progress is not None:
                self.progress(
                    sent,
                    file_size,
                )

            block_number = (
                block_number + 1
            ) & 0xFF

        if (
                file_size == 0
                and self.progress is not None
        ):
            self.progress(0, 0)

    def _send_packet(
            self,
            packet: bytes,
    ):
        """
        Send one packet and wait for ACK.
        """
        for _ in range(self.retries):
            self._write_all(packet)

            response = self._read_byte()

            if response == ACK:
                return

            if response == NAK:
                continue

            if response == CAN:
                self._raise_if_cancelled()

            # Timeout or unrelated input causes a retry.

        raise YModemRetriesExceeded(
            "packet was not acknowledged"
        )

    def _wait_for_crc_request(
            self,
            *,
            timeout: float | None = None,
    ):
        """
        Wait for the receiver to request CRC mode.

        Unrelated bytes are ignored so that bootloader text may precede
        the protocol request.
        """
        wait_timeout = (
            self.timeout
            if timeout is None
            else timeout
        )
        deadline = time.monotonic() + wait_timeout

        cancel_count = 0

        while time.monotonic() < deadline:
            remaining = (
                deadline - time.monotonic()
            )

            response = self._read_byte(
                timeout=min(
                    self.timeout,
                    remaining,
                )
            )

            if response == CRC_REQUEST:
                return

            if response == CAN:
                cancel_count += 1

                if cancel_count >= 2:
                    raise YModemCancelled(
                        "receiver cancelled transfer"
                    )
            else:
                cancel_count = 0

        raise YModemTimeout(
            "receiver did not request CRC-mode transfer"
        )

    def _finish_file(self):
        """
        Complete the sender side of the EOT handshake.

        Standard exchange:

            sender   -> EOT
            receiver -> NAK
            sender   -> EOT
            receiver -> ACK

        An immediate ACK is also accepted for compatibility with receivers
        that use a one-EOT exchange.
        """
        for _ in range(self.retries):
            self._write_control(EOT)
            response = self._read_byte()

            if response == ACK:
                return

            if response == CAN:
                self._raise_if_cancelled()

            if response != NAK:
                continue

            self._write_control(EOT)
            response = self._read_byte()

            if response == ACK:
                return

            if response == CAN:
                self._raise_if_cancelled()

        raise YModemRetriesExceeded(
            "receiver did not acknowledge end of file"
        )

    def _send_batch_end(self):
        payload = make_empty_header_payload()
        packet = make_packet(0, payload)

        self._send_packet(packet)

    def _raise_if_cancelled(self):
        """
        Treat two consecutive CAN bytes as cancellation.

        A single CAN is ignored as possible line noise.
        """
        second = self._read_byte(
            timeout=self.timeout,
        )

        if second == CAN:
            raise YModemCancelled(
                "receiver cancelled transfer"
            )


class YModemReceiver(_YModemTransport):
    """
    Receive one complete YMODEM batch.

    receive() returns a tuple containing the paths of all files received
    in the batch.
    """

    def __init__(
            self,
            transport,
            *,
            timeout: float = 10.0,
            retries: int = 10,
            startup_timeout: float = 60.0,
            progress: Callable[
                [Path, int, int | None],
                None,
            ] | None = None,
    ):
        super().__init__(
            transport,
            timeout=timeout,
            retries=retries,
        )

        if startup_timeout <= 0:
            raise ValueError(
                "startup_timeout must be greater than zero"
            )

        self.startup_timeout = startup_timeout
        self.progress = progress

    def receive(
            self,
            output_dir,
            *,
            overwrite: bool = False,
    ) -> tuple[Path, ...]:
        """
        Receive all files in one YMODEM batch.

        Files are first written with a .part suffix and atomically moved
        into place after successful validation.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        output_dir = output_dir.resolve()

        previous_timeout = getattr(
            self.transport,
            "timeout",
            None,
        )

        received = []
        started = False

        try:
            self.transport.timeout = self.timeout

            header_packet = self._request_header_packet(
                timeout=self.startup_timeout,
            )
            started = True

            while True:
                header = parse_header_payload(
                    header_packet.payload
                )

                if header is None:
                    self._write_control(ACK)
                    return tuple(received)

                destination = self._safe_destination(
                    output_dir,
                    header.filename,
                )

                if destination.exists() and not overwrite:
                    raise FileExistsError(destination)

                self._write_control(ACK)
                self._write_control(CRC_REQUEST)

                self._receive_file(
                    destination,
                    expected_size=header.file_size,
                )

                received.append(destination)

                header_packet = self._request_header_packet()

        except Exception:
            if started:
                self._cancel_quietly()

            raise

        finally:
            self.transport.timeout = previous_timeout

    def _request_header_packet(
            self,
            *,
            timeout: float | None = None,
    ) -> YModemPacket:
        """
        Request and receive a valid block-zero packet.
        """
        total_timeout = (
            self.timeout
            if timeout is None
            else timeout
        )
        deadline = time.monotonic() + total_timeout

        attempts = 0

        while (
                attempts < self.retries
                and time.monotonic() < deadline
        ):
            self._write_control(CRC_REQUEST)

            remaining = (
                deadline - time.monotonic()
            )

            start = self._read_byte(
                timeout=min(
                    self.timeout,
                    max(0.0, remaining),
                )
            )

            if start is None:
                attempts += 1
                continue

            if start == CAN:
                self._raise_if_cancelled()
                attempts += 1
                continue

            if start not in (SOH, STX):
                # Ignore bootloader or sender text while waiting.
                continue

            try:
                packet = self._read_packet_after_start(
                    start
                )
            except (
                    YModemTimeout,
                    YModemProtocolError,
            ):
                self._write_control(NAK)
                attempts += 1
                continue

            if packet.block_number != 0:
                self._write_control(NAK)
                attempts += 1
                continue

            if len(packet.payload) != HEADER_BLOCK_SIZE:
                self._write_control(NAK)
                attempts += 1
                continue

            return packet

        raise YModemRetriesExceeded(
            "did not receive a valid YMODEM block-zero header"
        )

    def _receive_file(
            self,
            destination: Path,
            *,
            expected_size: int | None,
    ):
        """
        Receive one file after its header has been acknowledged.
        """
        temporary = destination.with_name(
            destination.name + ".part"
        )

        if temporary.exists():
            temporary.unlink()

        expected_block = 1
        bytes_written = 0
        failed_packets = 0

        try:
            with temporary.open("wb") as file:
                while True:
                    start = self._read_byte()

                    if start is None:
                        failed_packets += 1

                        if failed_packets >= self.retries:
                            raise YModemRetriesExceeded(
                                "timed out waiting for a data packet"
                            )

                        self._write_control(NAK)
                        continue

                    if start == EOT:
                        self._finish_receive_file()
                        break

                    if start == CAN:
                        self._raise_if_cancelled()
                        continue

                    if start not in (SOH, STX):
                        # Ignore unrelated bytes rather than corrupting
                        # the current packet sequence.
                        continue

                    try:
                        packet = self._read_packet_after_start(
                            start
                        )
                    except (
                            YModemTimeout,
                            YModemProtocolError,
                    ):
                        failed_packets += 1

                        if failed_packets >= self.retries:
                            raise YModemRetriesExceeded(
                                "too many invalid data packets"
                            )

                        self._write_control(NAK)
                        continue

                    previous_block = (
                        expected_block - 1
                    ) & 0xFF

                    if packet.block_number == previous_block:
                        # The receiver's previous ACK was probably lost.
                        # Acknowledge the retransmitted packet without
                        # writing it again.
                        self._write_control(ACK)
                        continue

                    if packet.block_number != expected_block:
                        failed_packets += 1

                        if failed_packets >= self.retries:
                            raise YModemRetriesExceeded(
                                "too many out-of-sequence packets"
                            )

                        self._write_control(NAK)
                        continue

                    payload = packet.payload

                    if expected_size is not None:
                        remaining = (
                            expected_size - bytes_written
                        )

                        if remaining <= 0:
                            payload = b""
                        else:
                            payload = payload[:remaining]

                    file.write(payload)
                    bytes_written += len(payload)

                    self._write_control(ACK)

                    failed_packets = 0

                    if self.progress is not None:
                        self.progress(
                            destination,
                            bytes_written,
                            expected_size,
                        )

                    expected_block = (
                        expected_block + 1
                    ) & 0xFF

            if (
                    expected_size is not None
                    and bytes_written != expected_size
            ):
                raise YModemProtocolError(
                    f"expected {expected_size} bytes, "
                    f"received {bytes_written}"
                )

            os.replace(
                temporary,
                destination,
            )

        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

            raise

    def _finish_receive_file(self):
        """
        Complete the receiver side of the EOT handshake.

        Standard exchange:

            sender   -> EOT
            receiver -> NAK
            sender   -> EOT
            receiver -> ACK
        """
        self._write_control(NAK)

        for _ in range(self.retries):
            response = self._read_byte()

            if response == EOT:
                self._write_control(ACK)
                return

            if response == CAN:
                self._raise_if_cancelled()
                continue

            if response is None:
                self._write_control(NAK)
                continue

            self._write_control(NAK)

        raise YModemRetriesExceeded(
            "sender did not complete the EOT handshake"
        )

    def _raise_if_cancelled(self):
        """
        Treat two consecutive CAN bytes as cancellation.
        """
        second = self._read_byte(
            timeout=self.timeout,
        )

        if second == CAN:
            raise YModemCancelled(
                "sender cancelled transfer"
            )

    @staticmethod
    def _safe_destination(
            output_dir: Path,
            transmitted_name: str,
    ) -> Path:
        """
        Convert a remotely supplied filename into a safe local path.

        Directory information supplied by the sender is discarded.
        """
        filename = (
            transmitted_name
            .replace("\\", "/")
            .rsplit("/", 1)[-1]
        )

        if filename in ("", ".", ".."):
            raise YModemProtocolError(
                f"invalid transmitted filename: "
                f"{transmitted_name!r}"
            )

        destination = (
            output_dir / filename
        ).resolve()

        if destination.parent != output_dir:
            raise YModemProtocolError(
                "transmitted filename escapes output directory"
            )

        return destination
