# sertools

Interface for serial devices using pyserial.

## Installation

```bash
pip install sertools
```

## Features
- Query method with flexible configuration parameters for various response formats.
- Lightweight serial port terminal emulator.

## Usage
The SerialDevice instance may be called with a command string to send to the serial port and optional readback/terminator parameters.

```python
from sertools import SerialDevice
ser = SerialDevice()
ser('HELP')
```

## Development
```bash
git clone https://github.com/jbdoar/sertools
cd sertools
pip install -e .
```
