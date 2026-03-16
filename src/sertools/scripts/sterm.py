import argparse
import logging
import sys
import threading

import readchar

import sertools


log = logging.getLogger('sertools')


def configure_logging(logfile=None):
    """
    """
    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.propagate = False

    if logfile:
        file_handler = logging.FileHandler(logfile, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M%S'))
        log.addHandler(file_handler)


def reader(ser, stop_event):
    """
    """
    buf = bytearray()

    while not stop_event.is_set():
        try:
            n = ser.ser.in_waiting
            data = ser.ser.read(n or 1)
        except Exception:
            break

        if not data:
            continue

        text = data.decode(ser.encoding, errors='replace')
        sys.stdout.write(text)
        sys.stdout.flush()

        buf.extend(data)

        while True:
            i_crlf = buf.find(b'\r\n')
            i_cr = buf.find(b'\r')
            i_lf = buf.find(b'\n')

            matches = [(i, 2) for i in [i_crlf] if i != -1]
            matches += [(i, 1) for i in [i_cr, i_lf] if i != -1]

            if not matches:
                break

            i, nl_len = min(matches, key=lambda x: x[0])
            line = bytes(buf[:i]).decode(ser.encoding, errors='replace')
            del buf[:i + nl_len]

            if line:
                log.info('RX: %r', line)


def send_raw(ser, s):
    """
    """
    sys.stdout.write(s)
    sys.stdout.flush()
    ser.ser.write(s.encode(ser.encoding))


def terminal(ser):
    stop_event = threading.Event()
    threading.Thread(target=reader, args=(ser, stop_event), daemon=True).start()

    linebuf = []

    try:
        while True:
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                break

            if key == readchar.key.ESC:
                send_raw(ser, '\x1b')
            elif key == readchar.key.BACKSPACE:
                send_raw(ser, '\x08')
            elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                line = ''.join(linebuf)
                send_raw(ser, ser.newline_tx or '\r')
                if line:
                    log.info("TX: %r", line)
            else:
                send_raw(ser, key)
                linebuf.append(key)
    finally:
        stop_event.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('port')
    parser.add_argument('baudrate', type=int)
    parser.add_argument('--log', help='path to log file')
    args = parser.parse_args()

    configure_logging(args.log)

    ser = sertools.SerialDevice(
        port=args.port,
        baudrate=args.baudrate,
        newline_rx='\r',
        terminator=None,
        terminator_cmd=None,
    )

    try:
        terminal(ser)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
