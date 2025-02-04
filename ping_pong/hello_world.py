#!/usr/bin/python   
# Labvanced Ping-Pong example (send and receive data).

# This server waits to receive a "ping" message from a running labvanced experiment (which contains a name as a value).
# After receiving the "ping" it sends back a "pong" message to the running experiment containing the value "Hello {name}".

# To test this, run this script first and then start the following study on Labvanced https://www.labvanced.com/page/library/51053 

import asyncio
import json
import websockets
import datetime
import magic  # You'll need to install python-magic: pip install python-magic


IP_ADDRESS = '0.0.0.0'
WEBSOCKET_PORT = 8081


async def on_connect(websocket):
    print("websocket connection established")
    try:
        async for message in websocket:
            data = json.loads(message)
            # data has two fields 'msg' and 'data'. msg is the trigger / message, value is the variable value, both
            # defined in the 'send external trigger action' in your Labvanced experiment.
            received_value = data['value']
            received_msg = data['msg']

            # here you can make an if-elif for each of your triggers and depending on the type execute different code
            if received_msg == 'ping':
                # at this location you could add some code to send a trigger to an external device
                print("msg = {}, received_value = {}".format(received_msg, received_value))

                # this is how you send messages back to the Labvanced player. Specify a 'msg' field, which can be used
                # as a trigger and optionally send some data in the 'value' field. Depending on your application this
                # code can / should be placed at a different location.
                send_value = f"Hello {received_value}"
                await websocket.send(json.dumps({'msg': 'pong', 'value': send_value}))
            elif received_msg == 'anotherTrigger':
                # do something else here
                print("another trigger was received")
            else:
                # unsupported trigger
                print("unsupported event: {}".format(data))
    finally:
        print("connection lost")


# Updated server startup code
async def main():
    async with websockets.serve(on_connect, IP_ADDRESS, WEBSOCKET_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
