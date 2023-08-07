# Simple Hello World Example

This example illustrates how a value (name of the participant) is send from a running labvanced study to a custom python server, which then replies with a customized greeting "Hello {name}" that is then displayed as a stimulus back to the participant.

To test this, you can use the Labvanced template study: [https://www.labvanced.com/page/library/51053](https://www.labvanced.com/page/library/51053).

# How to deploy your own server:

If you want to deploy your own server online which receives and sends participant data, you should register your own domain and setup your server (or reverse-proxy) with a TLS certificate to encrypt the communication. For example, [Let's Encrypt](https://letsencrypt.org/) is a nonprofit certificate authority that provides free TLS certificates.

After you deployed your server, enable the websocket connection in the labvanced study settings and enter `wss://YOUR_DOMAIN` as the websocket address, where `YOUR_DOMAIN` should be replaced with your own domain name.