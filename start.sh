#!/bin/bash
LD_LIBRARY_PATH=/app ./llama-server -m /app/model.gguf --host 0.0.0.0 --port 8080 -c 2048 &
sleep 10
python /app/bot.py
