FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     fonts-dejavu-core     libfreetype6-dev     libjpeg-dev     libpng-dev     zlib1g-dev     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py /app/

CMD ["python", "/app/bot.py"]
