# Binary Data Transfer World Example

This example illustrates how a transfer binary data (images / audio / video) via websocket and stores this locally on your computer..

# How to deploy your own server:

If you want to deploy your own server online which receives and sends participant data, you should register your own domain and setup your server (or reverse-proxy) with a TLS certificate to encrypt the communication. For example, [Let's Encrypt](https://letsencrypt.org/) is a nonprofit certificate authority that provides free TLS certificates.

After you deployed your server, enable the websocket connection in the labvanced study settings and enter `wss://YOUR_DOMAIN` as the websocket address, where `YOUR_DOMAIN` should be replaced with your own domain name.