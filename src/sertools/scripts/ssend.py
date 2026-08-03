# scripts/ssend.py

"""
Send a text or binary file to a serial device.
"""

import argparse
import sys
import time
from pathlib import Path

import serial

import sertools


NEWLINES = {
    'raw': None,
    'cr': b'\r',
    'lf': b'\n',
    'crlf': b'\r\n',
}


def load_file(
        path,
        *,
        text=False,
        encoding='utf-8',
        newline='raw',
):
    """
    Load a file for transmission.

    Binary files are returned unchanged. In text mode, line endings may be
    normalized before encoding.
    """
    path = Path(path)

    if not text:
        return path.read_bytes()

    content = path.read_text(encoding=encoding)
    target = NEWLINES[newline]

    if target is not None:
        content = content.replace('\r\n', '\n')
        content = content.replace('\r', '\n')
        content = content.replace(
            '\n',
            target.decode('ascii'),
        )

    return content.encode(encoding)


def write_all(ser, data):
    """
    Write all bytes, handling partial serial writes.
    """
    sent = 0

    while sent < len(data):
        written = ser.ser.write(data[sent:])

        if written <= 0:
            raise serial.SerialTimeoutException(
                'serial write returned without sending data'
            )

        sent += written

    return sent


def show_progress(sent, total):
    """
    Display byte-oriented transmission progress.
    """
    percent = 100.0 if total == 0 else 100.0 * sent / total

    sys.stderr.write(
        f'\rSent {sent}/{total} bytes '
        f'({percent:6.2f}%)'
    )
    sys.stderr.flush()


def send_file(
        ser,
        data,
        *,
        chunk_size=1024,
        delay=0.0,
        line_delay=None,
        show_progress_output=True,
):
    """
    Send data through an open serial connection.

    If line_delay is provided, send one complete line at a time and pause
    between lines. Otherwise, send fixed-size chunks.
    """
    total = len(data)
    sent = 0

    if line_delay is not None:
        pieces = data.splitlines(keepends=True)
        pause = line_delay
    else:
        pieces = (
            data[i:i + chunk_size]
            for i in range(0, total, chunk_size)
        )
        pause = delay

    for piece in pieces:
        sent += write_all(ser, piece)

        if show_progress_output:
            show_progress(sent, total)

        if pause:
            time.sleep(pause)

    ser.ser.flush()

    if show_progress_output:
        if total == 0:
            show_progress(0, 0)

        sys.stderr.write('\n')
        sys.stderr.flush()

    return sent


def main():
    parser = argparse.ArgumentParser(
        description='Send a text or binary file to a serial device.',
    )

    parser.add_argument('port')
    parser.add_argument('baudrate', type=int)
    parser.add_argument('file', type=Path)

    parser.add_argument(
        '--data',
        type=int,
        choices=(5, 6, 7, 8),
        default=8,
        help='number of data bits',
    )

    parser.add_argument(
        '--parity',
        choices=('none', 'even', 'odd', 'mark', 'space'),
        default='none',
    )

    parser.add_argument(
        '--stop',
        type=float,
        choices=(1, 1.5, 2),
        default=1,
        help='number of stop bits',
    )

    parser.add_argument(
        '--flow',
        choices=('none', 'xonxoff', 'rtscts', 'dsrdtr'),
        default='none',
        help='flow-control mode',
    )

    parser.add_argument(
        '--text',
        action='store_true',
        help='read the input as text rather than raw bytes',
    )

    parser.add_argument(
        '--encoding',
        default='utf-8',
        help='text-file encoding used with --text (default: utf-8)',
    )

    parser.add_argument(
        '--newline',
        choices=tuple(NEWLINES),
        default='raw',
        help=(
            'normalize text-file newlines before sending; '
            'only applies with --text (default: raw)'
        ),
    )

    parser.add_argument(
        '--chunk-size',
        type=int,
        default=1024,
        help='maximum bytes written at once (default: 1024)',
    )

    parser.add_argument(
        '--delay',
        type=float,
        default=0.0,
        help='delay in seconds between chunks (default: 0)',
    )

    parser.add_argument(
        '--line-delay',
        type=float,
        default=None,
        help=(
            'send one line at a time with this delay in seconds '
            'between lines; requires --text'
        ),
    )

    parser.add_argument(
        '--write-timeout',
        type=float,
        default=None,
        help='serial write timeout in seconds',
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
        help='suppress progress output',
    )

    args = parser.parse_args()

    if args.chunk_size <= 0:
        parser.error('--chunk-size must be greater than zero')

    if args.delay < 0:
        parser.error('--delay cannot be negative')

    if args.line_delay is not None and args.line_delay < 0:
        parser.error('--line-delay cannot be negative')

    if args.line_delay is not None and not args.text:
        parser.error('--line-delay requires --text')

    if args.line_delay is not None and args.delay:
        parser.error('--delay and --line-delay cannot be used together')

    if args.newline != 'raw' and not args.text:
        parser.error('--newline requires --text')

    if not args.file.is_file():
        parser.error(f'file not found: {args.file}')

    parity = {
        'none': serial.PARITY_NONE,
        'even': serial.PARITY_EVEN,
        'odd': serial.PARITY_ODD,
        'mark': serial.PARITY_MARK,
        'space': serial.PARITY_SPACE,
    }[args.parity]

    try:
        data = load_file(
            args.file,
            text=args.text,
            encoding=args.encoding,
            newline=args.newline,
        )
    except (OSError, UnicodeError) as exc:
        parser.exit(
            1,
            f'Error: unable to read {args.file!s}: {exc}\n',
        )

    try:
        ser = sertools.SerialDevice(
            port=args.port,
            baudrate=args.baudrate,
            newline_rx='\r',
            terminator=None,
            terminator_cmd=None,
            bytesize=args.data,
            parity=parity,
            stopbits=args.stop,
            xonxoff=args.flow == 'xonxoff',
            rtscts=args.flow == 'rtscts',
            dsrdtr=args.flow == 'dsrdtr',
            timeout=args.write_timeout,
        )
    except serial.SerialException as exc:
        parser.exit(
            1,
            f'Error: unable to open {args.port!r}: {exc}\n',
        )

    try:
        sent = send_file(
            ser,
            data,
            chunk_size=args.chunk_size,
            delay=args.delay,
            line_delay=args.line_delay,
            show_progress_output=not args.quiet,
        )
    except (serial.SerialException, OSError) as exc:
        parser.exit(
            1,
            f'\nError: transmission failed: {exc}\n',
        )
    finally:
        ser.close()

    if not args.quiet:
        sys.stderr.write(
            f'Finished sending {sent} bytes from {args.file}\n'
        )


if __name__ == '__main__':
    main()
