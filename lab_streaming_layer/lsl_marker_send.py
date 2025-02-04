"""Example program to demonstrate how to forward string-valued markers from labvanced into LSL."""

import asyncio
import json
import websockets

from pylsl import StreamInfo, StreamOutlet, cf_string


IP_ADDRESS = '0.0.0.0'
WEBSOCKET_PORT = 8081


async def on_connect(websocket):
    print("websocket connection established")

    # first create a new stream info (here we set the name to MyMarkerStream,
    # the content-type to Markers, 1 channel, irregular sampling rate,
    # and string-valued data) The last value would be the locally unique
    # identifier for the stream as far as available, e.g.
    # program-scriptname-subjectnumber (you could also omit it but interrupted
    # connections wouldn't auto-recover). The important part is that the
    # content-type is set to 'Markers', because then other programs will know how
    #  to interpret the content
    info = StreamInfo(name='labvanced_stream_1', type='Markers', channel_count=1, nominal_srate=0, channel_format=cf_string, source_id='myuidw43536')

    # next make an outlet
    outlet = StreamOutlet(info)

    try:
        async for message in websocket:
            data = json.loads(message)
            # data has two fields 'msg' and 'data'. msg is the trigger / message, value is the variable value, both
            # defined in the 'send external trigger action' in your Labvanced experiment.
            received_value = data['value']
            received_msg = data['msg']
            if received_msg == 'lsl_marker':
                print("msg = {}, received_value = {}".format(received_msg, received_value))
                outlet.push_sample([received_value])
            else:
                print("unsupported event: {}".format(data))
    finally:
        print("connection lost")


async def main():
    async with websockets.serve(on_connect, IP_ADDRESS, WEBSOCKET_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())