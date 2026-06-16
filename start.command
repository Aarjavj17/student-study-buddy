#!/bin/bash
cd "$(dirname "$0")"
echo "==============================================="
echo "Starting Student Buddy Flask Server..."
echo "Please keep this Terminal window open while using the app."
echo "Press Ctrl+C in this window to stop the server."
echo "==============================================="

# Parse USE_HTTPS from .env file (default to false)
USE_HTTPS="false"
if [ -f .env ]; then
    ENV_VAL=$(grep -E "^USE_HTTPS=" .env | cut -d'=' -f2 | tr -d ' "\r\n')
    if [ ! -z "$ENV_VAL" ]; then
        USE_HTTPS="$ENV_VAL"
    fi
fi

# Automatically open the browser tab after 2 seconds
if [ "$USE_HTTPS" = "true" ]; then
    (sleep 2 && open "https://127.0.0.1:5000/") &
else
    (sleep 2 && open "http://127.0.0.1:5000/") &
fi

python3 app.py
