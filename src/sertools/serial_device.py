"""sertools.py module, a thin pyserial wrapper"""


"""

"""

import logging
import time

import serial


log = logging.getLogger(__name__)


class SerialDevice:
    """Thin wrapper for pyserial.Serial class.
    Provides a flexible query method for sending commands and receiving responses.
    Responses are always either a str (single line) or list of str (multiline).
    
    Parameters
    ----------
    port : str
    baudrate : int
    timeout : float
    encoding : str
    newline_tx : str
    newline_rx : str
    terminator : str
    terminator_cmd : str

    Examples
    --------
    >>> dut = SerialDevice(port='COM42',
                           baudrate=460800,
                           timeout=None,
                           newline_tx='\r',
                           newline_rx='\r\n',
                           terminator='Ok',
                           terminator_cmd='\r')
    """
    def __init__(self, *,
                 port: str | None = None,
                 baudrate: int = 9600,
                 timeout: float | None = None,
                 encoding: str = 'ascii',
                 newline_tx: str = '\r',
                 newline_rx: str = '\r',
                 terminator: str | None = None,
                 terminator_cmd: str | None = None,
                 bytesize: int = serial.EIGHTBITS,
                 parity: str = serial.PARITY_NONE,
                 stopbits: float = serial.STOPBITS_ONE,
                 xonxoff: bool = False,
                 rtscts: bool = False,
                 dsrdtr: bool = False):

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.encoding = encoding
        self.newline_tx = newline_tx
        self.newline_rx = newline_rx
        self.terminator = terminator
        self.terminator_cmd = terminator_cmd
        self._rx_buffer = bytearray()
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.xonxoff = xonxoff
        self.rtscts = rtscts
        self.dsrdtr = dsrdtr

        self.ser = serial.Serial(port=port,
                                 baudrate=baudrate,
                                 timeout=timeout,
                                 bytesize=bytesize,
                                 parity=parity,
                                 stopbits=stopbits,
                                 xonxoff=xonxoff,
                                 rtscts=rtscts,
                                 dsrdtr=dsrdtr,
                                 )


    def __repr__(self):
        return (
            f"{self.__class__.__name__}(\n"
            f"    port={self.port!r},\n"
            f"    baudrate={self.baudrate},\n"
            f"    timeout={self.timeout!r},\n"
            f"    encoding={self.encoding},\n"
            f"    newline_tx={self.newline_tx!r},\n"
            f"    newline_rx={self.newline_rx!r},\n"
            f"    terminator={self.terminator!r},\n"
            f"    terminator_cmd={self.terminator_cmd!r},\n"
            f"    bytesize={self.bytesize},\n"
            f"    parity={self.parity!r},\n"
            f"    stopbits={self.stopbits},\n"
            f"    xonxoff={self.xonxoff},\n"
            f"    rtscts={self.rtscts},\n"
            f"    dsrdtr={self.dsrdtr},\n"
        )


    def __str__(self):
        return f"{self.port} @ {self.baudrate}"


    def __call__(self, command: str, **kwargs) -> str | list[str]:
        """Passes `command` and other params along to `self.query`."""

        response = self.query(command, **kwargs)
        return response


    def open(self) -> None:
        """Open port."""
        self.ser.open()


    def close(self) -> None:
        """Close port."""
        self.ser.close()


    def flush(self) -> None:
        """Reset input and output buffers."""
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()


    def write(self, command: str,
              newline_tx: str | None = None,
              append_newline: bool = True) -> int:
        """Write command to port.

        Parameters
        ----------
        command : str
            Command sent to device.
        newline_tx : str, optional
            Newline character denoting end of line sent.
            Defaults to `self.newline_tx'
        append_newline : bool, optional
            Optionally append newline_tx to command if not already present.
            Defaults to True.

        Returns
        -------
        int
            Number of bytes sent to port.

        Examples
        --------
        >>> TBD
        """
        newline_tx = self.newline_tx if newline_tx is None else newline_tx

        if append_newline and not command.endswith(newline_tx):
            command += newline_tx

        log.info("TX: %r", command)
        tx = command.encode(self.encoding)
        return self.ser.write(tx)


    def readline(self, newline_rx: str | None = None,
                 timeout: float | None = None) -> str:
        """Read a line from device.

        Parameters
        ----------
        newline_rx : str, optional
            Newline character denoting end of line read.
            Defaults to self.newline_rx.
        timeout : float, optional
            Timeout.
            Defaults to self.timeout.

        Returns
        -------
        line : str

        Examples
        --------
        >>> TBD
        """
        newline_rx = self.newline_rx if newline_rx is None else newline_rx
        timeout = self.timeout if timeout is None else timeout

        nl = newline_rx.encode(self.encoding)
        t0 = time.monotonic()
        line_bytes = None

        while True:
            i = self._rx_buffer.find(nl)
            if i != -1:
                line_bytes = self._rx_buffer[:i]
                del self._rx_buffer[:i + len(nl)]
                break

            if timeout is not None and time.monotonic() - t0 >= timeout:
                if self._rx_buffer:
                    line_bytes = bytes(self._rx_buffer)
                    self._rx_buffer.clear()
                else:
                    line_bytes = b''
                break

            n = self.ser.in_waiting
            if n:
                self._rx_buffer.extend(self.ser.read(n))
            else:
                time.sleep(0.005)

        line = line_bytes.decode(self.encoding, errors='replace').strip()
        if line:
            log.info("RX: %r", line)
        return line
    

    def query(self, command: str, **kwargs) -> str | list[str]:
        """Primary method for sending command and receiving response.

        Parameters
        ----------
        command : str
            Command sent to device.

        **kwargs
            Additional read options.
            May override instance defaults such as `newline_tx`, `newline_rx`, etc.

        newline_tx : str, optional
            Newline character for `self.write`.
            Defaults to `self.newline_tx`.
        newline_rx : str, optional
            Newline character for `self.readline`.
            Defaults to `self.newline_rx`.
        timeout : float, optional
            Read timeout for whole query, separate from `self.ser.timeout`.
            Defaults to `self.timeout`.
        terminator : str, optional
            Ends readline loop when `terminator` in `line`.
            Defaults to `self.terminator`.
        terminator_cmd : str, optional
            Command string sent to port that triggers device to emit `terminator`.
            Defaults to `self.terminator_cmd`.
        strip_terminator : bool, optional
            Remove `terminator` line from end of `response`.
            Defaults to `True`.
        terminator_delay : float, optional
            Wait `terminator_delay` seconds before sending `terminator_cmd`.
            Defaults to 0.
        terminator_idle_timeout : float | None, optional
            After `terminator_cmd` is sent, return once no data have been received for `terminator_idle_timeout` seconds.
            Defaults to None.
        num_lines : int, optional
            Stops read when `len(response) == num_lines`.
            Defaults to None.

        Returns
        -------
        response : str or list[str]

        Examples
        --------
        >>> TBD
        """

        newline_tx = kwargs.get('newline_tx', self.newline_tx)
        newline_rx = kwargs.get('newline_rx', self.newline_rx)
        timeout = kwargs.get('timeout', self.timeout)
        terminator = kwargs.get('terminator', self.terminator)
        terminator_cmd = kwargs.get('terminator_cmd', self.terminator_cmd)
        strip_terminator = kwargs.get('strip_terminator', True)
        terminator_delay = kwargs.get('terminator_delay', 0)
        terminator_idle_timeout = kwargs.get('terminator_idle_timeout', None)
        num_lines = kwargs.get('num_lines', None)
        
        # do we want to check if stuff is getting received?
        # like suppose when we connect, the device is already continuously emitting data...

        if (terminator_idle_timeout is not None and terminator_idle_timeout <= 0):
            raise ValueError('terminator_idle_timeout must be positive or None')
        
        self.flush()
        
        self.write(command, newline_tx=newline_tx, append_newline=True)

        response = []
        t0 = time.monotonic()
        sent_terminator = False
        saw_terminator = False
        last_rx_at = None
        
        while True:
            now = time.monotonic()

            # Start with remaining overall query timeout
            if timeout is None:
                remaining = None
            else:
                remaining = timeout - (now - t0)
                if remaining <= 0:
                    break

            # Send terminator_cmd once its delay has elapsed.
            # Before then, ensure readline() cannot block past the scheduled send time.
            # Toggle sent_terminator to True so it only sends it once.
            if (terminator_cmd is not None and not sent_terminator):
                delay_remaining = terminator_delay - (now - t0)

                if delay_remaining <= 0:
                    self.write(terminator_cmd, newline_tx=newline_tx, append_newline=False)
                    sent_terminator = True
                    last_rx_at = now
                else:
                    remaining = (
                        delay_remaining
                        if remaining is None
                        else min(remaining, delay_remaining)
                    )

            # Once terminator_cmd has been sent, limit readline() by the remaining allowed receive-idle period.
            if (sent_terminator
                and terminator_idle_timeout is not None
                and last_rx_at is not None):
                
                idle_remaining = (terminator_idle_timeout - (now - last_rx_at))

                if idle_remaining <= 0:
                    break

                remaining = (idle_remaining if remaining is None
                             else min(remaining, idle_remaining))
                
            # Read line and append to response if it's not empty
            line = self.readline(newline_rx=newline_rx, timeout=remaining)

            if line:
                now = time.monotonic()
                response.append(line)

                if sent_terminator:
                    last_rx_at = now

            # Optionally end read at num_lines
            if num_lines is not None and len(response) >= num_lines:
                break

            # Optionally end read at terminator
            if (terminator is not None and line and terminator in line):
                saw_terminator = True
                break

        # Optionally remove terminator from response.
        if (strip_terminator
            and response
            and terminator
            and saw_terminator
            and terminator in response[-1]):
            
            response = response[:-1]

        # If response is single line, return as str
        if len(response) == 1:
            response = response[0]

        # clear 'self._rx_buffer'
        self._rx_buffer = bytearray()

        # flush
        if self.ser.in_waiting != 0:
            self.flush()

        return response

