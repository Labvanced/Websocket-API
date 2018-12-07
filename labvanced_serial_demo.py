#!/usr/bin/python   
# Labvanced External Device Synchronization Example.

# This server waits to receive a "set_rts_on" message or a "set_rts_off" message from a running experiment.
# It sets the rts serial line to on or off depending on the message.

# The following packages must be installed on your system
import asyncio
import json
import websockets
import serial

# You need to change the port name depending on your hardware setup:
# Usually on windows the port name is something like "COM3" and on linux something like "/dev/ttyS3"
ser = serial.Serial(port="COM3") 
ser.rts = False

async def on_connect(websocket, path):
    try:
        async for message in websocket:
            data = json.loads(message)
            # data has two fields 'msg' and 'data'. msg is the trigger / message, value is the variable value, both
            # defined in the 'send external trigger action' in your Labvanced experiment.
            received_value = data['value']
            received_msg = data['msg']

            # here you can make an if-elif for each of your triggers and depending on the type execute different code
            if received_msg == 'set_rts_on':
                print("setting rts line to on")
                ser.rts = True # this sets the RTS line voltage
            elif received_msg == 'set_rts_off':
                print("setting rts line to off")
                ser.rts = False # this sets the RTS line voltage
            else:
                print("unsupported event: {}".format(data))
    finally:
        print("connection lost")

# Make sure that the IP address and port match with the Labvanced study settings.
asyncio.get_event_loop().run_until_complete(websockets.serve(on_connect, 'localhost', 8081))
asyncio.get_event_loop().run_forever()
