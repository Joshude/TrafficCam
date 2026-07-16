FROM python:3.11-slim

# System-Abhaengigkeiten fuer OpenCV (headless) + FFmpeg fuer RTSP
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY run.py .

ENV CONFIG=/config/config.yaml

EXPOSE 8088
CMD ["python", "run.py"]
