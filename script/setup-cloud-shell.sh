#!/bin/bash
# install ngrok
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc   | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null   && echo "deb https://ngrok-agent.s3.amazonaws.com buster main"   | sudo tee /etc/apt/sources.list.d/ngrok.list   && sudo apt update   && sudo apt install ngrok

# activate venv
.venv/bin/activate

# start ngrok
ngrok http --url=workable-adjusted-foxhound.ngrok-free.app 8000

