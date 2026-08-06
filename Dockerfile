FROM python:3.11

RUN apt-get update && apt-get install -y     libsndfile1     ffmpeg     espeak-ng     g++     gcc     make     libopenblas-dev     liblapack-dev     libgomp1     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch CPU (легче, без CUDA)
RUN pip install --no-cache-dir torch==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY reference.wav .

ENV PORT=5000
EXPOSE 5000

CMD ["python", "server.py"]
