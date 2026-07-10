FROM python:3.11-slim

# System deps required by opencv / mediapipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Use the lighter local requirements (no LLM/legacy deps) by default.
COPY requirements.local.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# SKYN Engine v2 — trained models (torch CPU + ultralytics + transformers).
# Build with --build-arg SKYN_ML=0 to skip and fall back to classical CV.
ARG SKYN_ML=1
COPY requirements.ml.txt ./requirements.ml.txt
RUN if [ "$SKYN_ML" = "1" ]; then pip install --no-cache-dir -r requirements.ml.txt; fi

COPY . .

# Download model weights at build time so the image is self-contained.
RUN if [ "$SKYN_ML" = "1" ]; then python scripts/download_models.py; fi

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
