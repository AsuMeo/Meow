FROM python:3.11

RUN apt-get update && apt-get install -y     libsndfile1     ffmpeg     g++     gcc     make     libopenblas-dev     liblapack-dev     libgomp1     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir cython numpy
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV PORT=5000
EXPOSE 5000

CMD ["python", "server.py"]
