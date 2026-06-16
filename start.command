#!/bin/bash
cd "$(dirname "$0")"
echo "==============================================="
echo "Starting Student Buddy Flask Server..."
echo "Please keep this Terminal window open while using the app."
echo "Press Ctrl+C in this window to stop the server."
echo "==============================================="

# Automatically open the browser tab after 2 seconds
(sleep 2 && open "https://127.0.0.1:5000/") &

python3 app.py
