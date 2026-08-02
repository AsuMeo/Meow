#!/bin/bash
./llama-server -m /app/model.gguf --host 0.0.0.0 --port 8080 -c 2048 -np 1 &

# Ждём пока сервер ответит
echo "Ждём llama-server..."
for i in {1..60}; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "llama-server готов!"
        break
    fi
    sleep 2
done

sleep 3
python /app/bot.py
