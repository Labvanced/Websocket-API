# Labvanced Websocket API

## Overview:
In this repository you will find a series of scripts demonstrating how to use the Labvanced Websocket API. Our examples here mainly use Python as it is one of the most common programming languages for such tasks. If you want to contribute, we warmly welcome your PR!

## What can this be used for:
The Labvanced Websocket API can be used to connect a Labvanced study to some external device at runtime. Some examples are:
 - An experiment where you want to send experimental triggers (e.g. trial/stimulus onset or participant response) from Labvanced to an EEG system, Eye-Tracking system, or some other local data recording device. 
 - An experiment where you want to send online recorded data over the internet to some other server/API that processes it (e.g. some AI/ machine learning process or real time data analysis).
 - An experiment where you want to create bidirectional communication between Labvanced and some other process which can run locally or remotely (E.g. for BCI, biofeedback, or other closed-loop systems). 
 
 
## How to use it:
 1. Setup your study in Labvanced and in the study settings input an IP address and port (where the websocket server should run).
 2. Clone this repository
 3. Install Python and PIP (Pythons package manager)
 4. Install the dependencies (pip install)
 5. Select the script you want to run (e.g. "helloWorld.py" ) and make sure the IP and port specification for the Websocket connection is matching what you entered in Labvanced.
 6. Type: "python helloWorld.py" # the script should be running now.
 7. Start your Labvanced experiment in the browser. Once you start the study, the local Python script will print "websocket connection established". If you see that message, you know the connection is working. You can use the following study as a sample: https://www.labvanced.com/page/library/4107    
 8. In your Labvanced study use the Websocket triggers to receive data in Labvanced and Websocket actions to send triggers and data from Labvanced. Check our documentation for more information: https://www.labvanced.com/content/learn/guide/task-editor/event-system.html#websocket-api-trigger
 9. Adapt the Python script according to your needs. E.g change the trigger names or how you want to send data/triggers to some external device like an EEG system. As each system requires slightly different settings it is not possible to write one script that covers all use cases. Please check your vendors' documentation. 


## How to contribute:
If you already have created a working script that uses our Websocket API, please make a pull request (PR). We are happy to include your work here and credit you for it. This will also help everyone in the community.

If you are planning a new project and need a customized script to connect your device/process, but don't know how to do this, please contact us. We will be happy to guide you along the way.

If your use case is general enough and there are good test cases, we might even help you directly with the implementation. However, this depends on our availability and the generalizability of your use case.


