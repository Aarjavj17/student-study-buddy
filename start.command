#!/bin/bash
cd "$(dirname "$0")"
echo "==============================================="
echo "Starting Student Buddy Flask Server..."
echo "Please keep this Terminal window open while using the app."
echo "Press Ctrl+C in this window to stop the server."
echo "==============================================="

python3 app.py
