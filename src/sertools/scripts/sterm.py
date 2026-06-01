"""
TODO:
- docstrings for functions
- configure tx/rx newline args
- optionally configure data, parity, stop bit, flow control
- optionally configure local echo
- handle port unavailable exceptions
"""


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
            # look for line breaks

            i_crlf = buf.find(b'\r\n')
            i_cr = buf.find(b'\r')
            i_lf = buf.find(b'\n')

            if i_crlf != -1 and (i_cr == -1 or i_crlf <= i_cr) and (i_lf == -1 or i_crlf <= i_lf):
                i, nl_len = i_crlf, 2

            elif i_cr != -1 and (i_lf == -1 or i_cr <= i_lf):
                if i_cr == len(buf) - 1:
                    break
                i, nl_len = i_cr, 1

            elif i_lf != -1:
                i, nl_len = i_lf, 1

            else:
                break
            
            raw = bytes(buf[:i + nl_len]).decode(ser.encoding, errors='replace')
            del buf[:i + nl_len]

            log.info('RX: %r', raw)
            

def send_raw(ser, s, local_echo=True):
    """
    """
    if local_echo:
        sys.stdout.write(s)
        sys.stdout.flush()

    ser.ser.write(s.encode(ser.encoding))


def terminal(ser, local_echo=True):
    stop_event = threading.Event()
    threading.Thread(target=reader, args=(ser, stop_event), daemon=True).start()

    linebuf = []

    def tx(s):
        send_raw(ser, s, local_echo=local_echo)
    
    try:
        while True:
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                break

            if key == readchar.key.ESC:
                tx('\x1b')
                
            elif key == readchar.key.BACKSPACE:
                tx('\x08')
                if linebuf:
                    linebuf.pop()
                    
            elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                line = ''.join(linebuf)
                nl = ser.newline_tx or '\r'
                tx(nl)
                #if line:
                log.info("TX: %r", line + nl)
                linebuf.clear()
                
            else:
                tx(key)
                linebuf.append(key)
                
    finally:
        stop_event.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('port')
    parser.add_argument('baudrate', type=int)
    parser.add_argument('--log', help='path to log file')
    parser.add_argument('--no-echo', action='store_true', help='disable local echo')
    args = parser.parse_args()

    configure_logging(args.log)

    ser = sertools.SerialDevice(
        port=args.port,
        baudrate=args.baudrate,
        newline_rx='\r',
        terminator=None,
        terminator_cmd=None,
    )

    local_echo = not args.no_echo
    
    try:
        terminal(ser, local_echo=local_echo)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
