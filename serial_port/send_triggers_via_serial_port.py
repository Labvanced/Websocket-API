#!/usr/bin/python   
# Labvanced Send triggers via serial port example.

# The following packages must be installed on your system
# you can use the pip package manager to install them
import asyncio
import json
import websockets
import serial
import time
import sys
import glob
PulseWidth = 0.01
serial_ports = []
scan_serial_ports = True
SERIAL_PORT = "COM3" #e.g COM3
IP_ADDRESS = 'localhost'
WEBSOCKET_PORT = 8081


async def on_connect(websocket):
    print("websocket connection established")
    # set up serial port connection
    try:
        ser_port = serial.Serial(port=SERIAL_PORT) 
        ser_port.write([0x00])
        time.sleep(PulseWidth)
    except:
        print("Error connecting to serial port: {}".format(SERIAL_PORT))
        raise Exception("Error connecting to serial port")

    print("Successful connected to serial port: {}".format(SERIAL_PORT) )

    try:
        async for message in websocket:
            data = json.loads(message)
            # data has two fields 'msg' and 'data'. msg is the trigger / message, value is the variable value, both
            # defined in the 'send external trigger action' in your Labvanced experiment.
            received_value = data['value'] # you might not need value if you just want to send a trigger type
            received_msg = data['msg']
            # here you can make an if-elif for each of your triggers and depending on the type execute different code
            if received_msg == 'trigger1':
                # the code inside here must be changed according to the vendor/trigger specification you want to send.
                print("trigger 1 was received")
                ser_port.write([0x01])
                # waiting and writing again for brain product EEG 
                time.sleep(PulseWidth)
                ser_port.write([0x00])

            elif received_msg == 'trigger2':
                # the code inside here must be changed according to the vendor/trigger specification you want to send.
                print("trigger 2 was received")
                ser_port.write([0x02])
                # waiting and writing again for brain product EEG 
                time.sleep(PulseWidth)
                ser_port.write([0x00])
            else:
                # unsupported trigger
                print("unsupported trigger: {}".format(received_msg))
    finally:
        print("connection lost")


def get_serial_ports():
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result

if(scan_serial_ports):
    serial_ports = get_serial_ports()
    if len(serial_ports)>0:
        SERIAL_PORT = serial_ports[0]

if SERIAL_PORT:
    # Updated server startup code
    async def main():
        async with websockets.serve(on_connect, IP_ADDRESS, WEBSOCKET_PORT):
            await asyncio.Future()  # run forever

    if __name__ == "__main__":
        asyncio.run(main())
else:
    print("no serial port found or specified")

