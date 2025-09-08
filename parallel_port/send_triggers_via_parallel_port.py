import asyncio
import json
import websockets
import time
import sys
# import glob # Not needed for parallel port
import parallel # Import the pyparallel library

PulseWidth = 0.01
PARALLEL_PORT_ADDRESS = 0x378 # Default for LPT1. Change if your parallel port has a different address.
IP_ADDRESS = 'localhost'
WEBSOCKET_PORT = 8081

# Global variable to hold the parallel port object
par_port = None

async def on_connect(websocket):
    global par_port
    print("websocket connection established")

    # Set up parallel port connection
    try:
        par_port = parallel.Parallel(PARALLEL_PORT_ADDRESS)
        # Ensure all data lines are low initially
        par_port.setData(0x00)
        time.sleep(PulseWidth)
    except Exception as e:
        print(f"Error connecting to parallel port at address: {PARALLEL_PORT_ADDRESS}. "
              f"Please ensure pyparallel is installed and the port is available. Error: {e}")
        raise Exception("Error connecting to parallel port")

    print(f"Successfully connected to parallel port at address: {PARALLEL_PORT_ADDRESS}")

    try:
        async for message in websocket:
            data = json.loads(message)
            received_value = data['value']
            received_msg = data['msg']

            if received_msg == 'trigger1':
                print("trigger 1 was received")
                # Send 0x01 to the parallel port data lines
                par_port.setData(0x01)
                time.sleep(PulseWidth)
                # Reset to 0x00
                par_port.setData(0x00)

            elif received_msg == 'trigger2':
                print("trigger 2 was received")
                # Send 0x02 to the parallel port data lines
                par_port.setData(0x02)
                time.sleep(PulseWidth)
                # Reset to 0x00
                par_port.setData(0x00)
            else:
                print(f"unsupported trigger: {received_msg}")
    finally:
        print("connection lost")
        if par_port:
            try:
                par_port.setData(0x00) # Ensure port is reset on disconnect
                print("Parallel port reset to 0x00.")
            except Exception as e:
                print(f"Error resetting parallel port: {e}")


async def main():
    async with websockets.serve(on_connect, IP_ADDRESS, WEBSOCKET_PORT):
        print(f"WebSocket server started on ws://{IP_ADDRESS}:{WEBSOCKET_PORT}")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())