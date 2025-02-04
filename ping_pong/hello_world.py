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
            # Check if the message is binary data
            if isinstance(message, bytes):
                # Detect file type using magic numbers
                mime = magic.Magic(mime=True)
                file_type = mime.from_buffer(message)
                
                # Map common MIME types to file extensions
                extension_map = {
                    'image/jpeg': '.jpg',
                    'image/png': '.png',
                    'image/gif': '.gif',
                    'image/webp': '.webp',
                    'video/mp4': '.mp4',
                    'video/webm': '.webm',
                    'audio/mpeg': '.mp3',
                    'audio/wav': '.wav',
                    'audio/x-wav': '.wav',
                    'audio/ogg': '.ogg',
                }
                
                # Get file extension or default to .bin if type unknown
                extension = extension_map.get(file_type, '.bin')
                
                # Generate filename with timestamp and proper extension
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"received_file_{timestamp}{extension}"
                
                # Save the binary data to a file
                with open(filename, 'wb') as f:
                    f.write(message)
                print(f"Saved {file_type} data to {filename}")
                
                # Send confirmation back to client
                await websocket.send(json.dumps({
                    'msg': 'file_received',
                    'value': filename,
                    'type': file_type
                }))
            else:
                # Handle JSON messages as before
                data = json.loads(message)
                received_value = data['value']
                received_msg = data['msg']

                if received_msg == 'ping':
                    print("msg = {}, received_value = {}".format(received_msg, received_value))
                    send_value = f"Hello {received_value}"
                    await websocket.send(json.dumps({'msg': 'pong', 'value': send_value}))
                elif received_msg == 'anotherTrigger':
                    print("another trigger was received")
                else:
                    print("unsupported event: {}".format(data))
    finally:
        print("connection lost")


# Updated server startup code
async def main():
    async with websockets.serve(on_connect, IP_ADDRESS, WEBSOCKET_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
