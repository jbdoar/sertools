# scripts/sterm.py

"""
Interactive serial terminal.
"""

import argparse
import logging
import sys
import threading

import readchar
import serial

import sertools


log = logging.getLogger('sertools')


SPECIAL_KEYS = {
    readchar.key.ESC: '\x1b',
    
    # navigation / editing keys
    readchar.key.HOME: '\x1b[H',
    readchar.key.END: '\x1b[F',
    readchar.key.INSERT: '\x1b[2~',
    readchar.key.DELETE: '\x1b[3~',
    readchar.key.PAGE_UP: '\x1b[5~',
    readchar.key.PAGE_DOWN: '\x1b[6~',
    readchar.key.BACKSPACE: '\x08',

    # arrow keys
    readchar.key.UP: '\x1b[A',
    readchar.key.DOWN: '\x1b[B',
    readchar.key.RIGHT: '\x1b[C',
    readchar.key.LEFT: '\x1b[D',
}

NEWLINE_TX = {
    'cr': '\r',
    'lf': '\n',
    'crlf': '\r\n',
    'none': '',
}


class NewlineNormalizer:
    TARGETS = {
        'auto': '\n',
        'cr': '\r',
        'lf': '\n',
        'crlf': '\r\n',
    }
    
    def __init__(self, mode):
        self.mode = mode
        self.pending_cr = False

    @property
    def target(self):
        return self.TARGETS[self.mode]

    def normalize(self, text):
        if self.mode == 'raw':
            return text

        if self.pending_cr:
            text = '\r' + text
            self.pending_cr = False

        if text.endswith('\r'):
            text = text[:-1]
            self.pending_cr = True

        text = text.replace('\r\n', '\n')
        text = text.replace('\r', '\n')
        text = text.replace('\n', self.target)

        return text

    def write(self, text):
        text = self.normalize(text)

        if text:
            sys.stdout.write(text)
            sys.stdout.flush()

    def flush(self):
        if not self.pending_cr:
            return ''

        self.pending_cr = False
        return self.target

    def close(self):
        text = self.flush()

        if text:
            sys.stdout.write(text)
            sys.stdout.flush()


def configure_logging(logfile=None):
    """
    Configure optional session logging.
    """
    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.propagate = False

    if logfile:
        file_handler = logging.FileHandler(logfile, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
            )
        )
        log.addHandler(file_handler)


def log_received_lines(buf, data, encoding):
    buf.extend(data)

    while True:
        i_crlf = buf.find(b'\r\n')
        i_cr = buf.find(b'\r')
        i_lf = buf.find(b'\n')

        if (
                i_crlf != -1
                and (i_cr == -1 or i_crlf <= i_cr)
                and (i_lf == -1 or i_crlf <= i_lf)
        ):
            i, newline_length = i_crlf, 2

        elif i_cr != -1 and (
                i_lf == -1 or i_cr <= i_lf
        ):
            if i_cr == len(buf) - 1:
                break

            i, newline_length = i_cr, 1

        elif i_lf != -1:
            i, newline_length = i_lf, 1

        else:
            break

        raw = bytes(buf[:i + newline_length]).decode(
            encoding,
            errors='replace',
        )
        del buf[:i + newline_length]

        log.info('RX: %r', raw)
    

def reader(ser, stop_event, newline_rx):
    """
    Read incoming serial data, display it, and log complete lines.
    """
    buf = bytearray()

    try:
        while not stop_event.is_set():
            try:
                n = ser.ser.in_waiting
                data = ser.ser.read(n or 1)
            except (serial.SerialException, OSError) as exc:
                if not stop_event.is_set():
                    sys.stderr.write(
                        f'\nSerial connection lost: {exc}\n'
                    )
                    stop_event.set()

                return

            if not data:
                continue

            text = data.decode(
                ser.encoding,
                errors='replace',
            )
            newline_rx.write(text)

            log_received_lines(
                buf,
                data,
                ser.encoding,
            )

    finally:
        newline_rx.close()
        

def send_raw(ser, s, local_echo=True):
    """
    """
    ser.ser.write(s.encode(ser.encoding))
    
    if local_echo:
        sys.stdout.write(s)
        sys.stdout.flush()


def terminal(
        ser,
        *,
        local_echo=True,
        newline_tx='\r',
        newline_rx=None,
):
    """
    Run the interactive terminal.
    """
    if newline_rx is None:
        newline_rx = NewlineNormalizer('raw')

    
    stop_event = threading.Event()
    
    threading.Thread(
        target=reader,
        args=(ser, stop_event, newline_rx),
        daemon=True,
    ).start()

    linebuf = []

    def tx(s):
        try:
            send_raw(
                ser,
                s,
                local_echo=local_echo,
            )
        except (serial.SerialException, OSError) as exc:
            if not stop_event.is_set():
                sys.stderr.write(
                    f'\nSerial connection lost: {exc}\n'
                )
                stop_event.set()
    
    try:
        while not stop_event.is_set():
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                break
                
            if key == readchar.key.BACKSPACE:
                tx(SPECIAL_KEYS[key])
                if linebuf:
                    linebuf.pop()
                    
            elif key in (
                    readchar.key.ENTER,
                    readchar.key.CR,
                    readchar.key.LF,
            ):
                line = ''.join(linebuf)
                
                tx(newline_tx)
                log.info("TX: %r", line + newline_tx)

                linebuf.clear()

            elif key in SPECIAL_KEYS:
                tx(SPECIAL_KEYS[key])

            elif len(key) == 1:
                # Ordinary characters and single-byte control characters.
                tx(key)

                if key.isprintable():
                    linebuf.append(key)

                else:
                    # Ignore unknown multi-character key sequences rather than
                    # transmitting terminal-control bytes to the serial device.
                    log.debug("Ignoring unmapped key sequence: %r", key)
                
    finally:
        stop_event.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('port')
    parser.add_argument('baudrate', type=int)

    parser.add_argument(
        '--data',
        type=int,
        choices=(5,6,7,8),
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
        '--newline-tx',
        choices=('cr', 'lf', 'crlf', 'none'),
        default='cr',
        help='newline sent on Enter (default: cr)',
    )

    parser.add_argument(
        '--newline-rx',
        choices=('raw', 'auto', 'cr', 'lf', 'crlf'),
        default='raw',
        help='normalize received newlines for display (default: raw)',
    )

    parser.add_argument('--log', help='path to log file')
    
    parser.add_argument('--no-echo', action='store_true', help='disable local echo')
    
    args = parser.parse_args()

    configure_logging(args.log)

    parity = {
        'none': serial.PARITY_NONE,
        'even': serial.PARITY_EVEN,
        'odd': serial.PARITY_ODD,
        'mark': serial.PARITY_MARK,
        'space': serial.PARITY_SPACE,
    }[args.parity]

    newline_tx = NEWLINE_TX[args.newline_tx]
    
    newline_rx = NewlineNormalizer(args.newline_rx)

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
        )
    except serial.SerialException as exc:
        parser.exit(1, f'Error: unable to open {args.port!r}: {exc}\n')
    
    try:
        terminal(
            ser,
            local_echo=not args.no_echo,
            newline_tx=newline_tx,
            newline_rx=newline_rx,
        )
    finally:
        ser.close()


if __name__ == "__main__":
    main()
