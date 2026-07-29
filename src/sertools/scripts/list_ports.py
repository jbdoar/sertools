"""List COM ports"""

import argparse

from serial.tools import list_ports


def main():
    """
    Uses serial.tools.list_ports() to list COM ports and associated attributes.
    If called with --verbose option, print all the attributes.
    Else, just the ports.

    Examples
    --------
    >>>list_ports
    >>>list_ports --verbose
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    ports = list_ports.comports()

    for port in ports:
        if args.verbose:
            print("Device: ", port.device)
            print("Name: ", port.name)
            print("Description: ", port.description)
            print("HWID: ", port.hwid)
            print("VID: ", port.vid)
            print("PID: ", port.pid)
            print("Serial Number: ", port.serial_number)
            print("Manufacturer: ", port.manufacturer)
            print("Product: ", port.product)
            print("Location: ", port.location)
            print()

        else:
            print(port.device)

            
if __name__ == '__main__':
    main()
