"""Example program to show how to read a multi-channel time series from LSL."""

import asyncio
import json
import websockets
from pylsl import StreamInlet, resolve_streams

IP_ADDRESS = '0.0.0.0'
WEBSOCKET_PORT = 8081


async def on_connect(websocket):
    print("websocket connection established")

    # first resolve a Markers stream on the network
    print("looking for a Markers stream...")
    streams = resolve_streams("name", "my_stream_1")

    # create a new inlet to read from the stream
    inlet = StreamInlet(streams[0])

    while True:
        try:
            sample, timestamp = inlet.pull_sample(timeout=1.0)
            if timestamp is not None:
                print(timestamp, sample)
                # forward lsl marker to Labvanced:
                await websocket.send(json.dumps({'msg': 'lsl_marker', 'value': sample[0]}))
            elif timestamp is None:
                continue

        except Exception as e:
            print(f"Error with LSL stream: {e}. Exiting...")
            break


async def main():
    async with websockets.serve(on_connect, IP_ADDRESS, WEBSOCKET_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())