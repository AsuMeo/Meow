FROM python:3.11

RUN apt-get update && apt-get install -y     libsndfile1     ffmpeg     g++     gcc     make     libopenblas-dev     liblapack-dev     libgomp1     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала ставим numpy и build tools
RUN pip install --no-cache-dir numpy==1.26.4 cython==3.0.10 setuptools wheel

# Ставим pyworld без изоляции — компилируется против установленного numpy
RUN pip install --no-cache-dir --no-build-isolation pyworld==0.3.5

# Остальные зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV PORT=5000
EXPOSE 5000

CMD ["python", "server.py"]
