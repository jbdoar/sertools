# scripts/ssend_ymodem.py

import argparse
from pathlib import Path

import serial

import sertools
from sertools.ymodem import YModemSender


def main():
    parser = argparse.ArgumentParser(
        description='Send a file using YMODEM.',
    )

    parser.add_argument('port')
    parser.add_argument('baudrate', type=int)
    parser.add_argument('file', type=Path)

    parser.add_argument(
        '--timeout',
        type=float,
        default=10.0,
    )

    parser.add_argument(
        '--retries',
        type=int,
        default=10,
    )

    parser.add_argument(
        '--block-size',
        type=int,
        choices=(128, 1024),
        default=1024,
    )

    args = parser.parse_args()

    ser = sertools.SerialDevice(
        port=args.port,
        baudrate=args.baudrate,
        newline_rx='\r',
        terminator=None,
        terminator_cmd=None,
    )

    try:
        sender = YModemSender(
            ser.ser,
            timeout=args.timeout,
            retries=args.retries,
            block_size=args.block_size,
        )

        sender.send(args.file)
    finally:
        ser.close()


if __name__ == '__main__':
    main()
