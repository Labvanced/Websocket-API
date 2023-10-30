"""Example program to show how to read a multi-channel time series from LSL."""

from pylsl import StreamInlet, resolve_stream, LostError
import asyncio
import json
import websockets


IP_ADDRESS = '0.0.0.0'
WEBSOCKET_PORT = 8081


async def on_connect(websocket, path):
    print("websocket connection established")

    # first resolve a Markers stream on the network
    print("looking for a Markers stream...")
    streams = resolve_stream("name", "my_stream_1")

    # create a new inlet to read from the stream
    inlet = StreamInlet(streams[0])

    while True:
        try:
            sample, timestamp = inlet.pull_sample(timeout=1.0)
            if timestamp is not None:
                print(timestamp, sample)
                # forward lsl marker to Labvanced:
                await websocket.send(json.dumps({'msg': 'lsl_marker', 'value': sample[0]}))

        except LostError:
            print("Lost connection to lsl stream. Exiting...")
            break


def main():
    # Make sure that the IP address and port match with the Labvanced study settings.
    asyncio.get_event_loop().run_until_complete(websockets.serve(on_connect, IP_ADDRESS, WEBSOCKET_PORT))
    asyncio.get_event_loop().run_forever()


if __name__ == '__main__':
    main()
