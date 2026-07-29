# scripts/srecv_ymodem.py

"""
Receive files from a serial device using YMODEM.
"""

import argparse
import sys
from pathlib import Path

import serial

import sertools
from sertools.ymodem import (
    YModemError,
    YModemReceiver,
)


def show_progress(path, received, total):
    if total is None:
        detail = f'{received} bytes'
    else:
        percent = (
            100.0
            if total == 0
            else 100.0 * received / total
        )
        detail = (
            f'{received}/{total} bytes '
            f'({percent:6.2f}%)'
        )

    sys.stderr.write(
        f'\rReceiving {path.name}: {detail}'
    )
    sys.stderr.flush()


def main():
    parser = argparse.ArgumentParser(
        description='Receive files using YMODEM.',
    )

    parser.add_argument('port')
    parser.add_argument('baudrate', type=int)

    parser.add_argument(
        'output_dir',
        type=Path,
        nargs='?',
        default=Path.cwd(),
    )

    parser.add_argument(
        '--overwrite',
        action='store_true',
    )

    parser.add_argument(
        '--timeout',
        type=float,
        default=10.0,
    )

    parser.add_argument(
        '--startup-timeout',
        type=float,
        default=60.0,
    )

    parser.add_argument(
        '--retries',
        type=int,
        default=10,
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
    )

    args = parser.parse_args()

    try:
        ser = sertools.SerialDevice(
            port=args.port,
            baudrate=args.baudrate,
            newline_rx='\r',
            terminator=None,
            terminator_cmd=None,
            timeout=args.timeout,
            write_timeout=args.timeout,
        )
    except serial.SerialException as exc:
        parser.exit(
            1,
            f'Error: unable to open '
            f'{args.port!r}: {exc}\n',
        )

    progress = None if args.quiet else show_progress

    try:
        receiver = YModemReceiver(
            ser.ser,
            timeout=args.timeout,
            startup_timeout=args.startup_timeout,
            retries=args.retries,
            progress=progress,
        )

        paths = receiver.receive(
            args.output_dir,
            overwrite=args.overwrite,
        )

    except (
            YModemError,
            serial.SerialException,
            OSError,
    ) as exc:
        parser.exit(
            1,
            f'\nError: YMODEM receive failed: {exc}\n',
        )

    finally:
        ser.close()

    if not args.quiet:
        sys.stderr.write('\n')

        for path in paths:
            sys.stderr.write(
                f'Received {path}\n'
            )


if __name__ == '__main__':
    main()
