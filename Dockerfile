FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     wget build-essential cmake git libgomp1     && rm -rf /var/lib/apt/lists/*

# llama.cpp — копируем ВСЮ папку bin с so-файлами
RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp &&     cd /tmp/llama.cpp &&     cmake -B build -DLLAMA_BUILD_SERVER=ON -DBUILD_SHARED_LIBS=OFF &&     cmake --build build --config Release -j$(nproc) &&     cp -r build/bin/* /app/ &&     rm -rf /tmp/llama.cpp

# Модель Qwen 0.5B
RUN wget -O /app/model.gguf "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py /app/
COPY start.sh /app/
RUN chmod +x /app/start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
