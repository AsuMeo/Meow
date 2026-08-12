FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py cloud.py music.py /app/
CMD ["python", "/app/server.py"]
