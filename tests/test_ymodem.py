from sertools.ymodem import (
    CPMEOF,
    SOH,
    YModemFileHeader,
    crc16_xmodem,
    make_empty_header_payload,
    make_header_payload,
    make_packet,
    pad_block,
    parse_header_payload,
)


def test_crc16_xmodem_known_value():
    assert crc16_xmodem(b"123456789") == 0x31C3


def test_make_packet_128_bytes():
    payload = bytes(128)

    packet = make_packet(7, payload)

    assert packet[0] == SOH
    assert packet[1] == 7
    assert packet[2] == 0xF8
    assert packet[3:131] == payload
    assert len(packet) == 133


def test_header_round_trip():
    payload = make_header_payload(
        "firmware.bin",
        12345,
    )

    header = parse_header_payload(payload)

    assert header == YModemFileHeader(
        filename="firmware.bin",
        file_size=12345,
    )


def test_empty_header_ends_batch():
    payload = make_empty_header_payload()

    assert parse_header_payload(payload) is None


def test_pad_block():
    result = pad_block(
        b"abc",
        128,
    )

    assert result == (
        b"abc"
        + bytes([CPMEOF]) * 125
    )
