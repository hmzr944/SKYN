# SKYN — image cloud tout-en-un : API + moteur ML + application web.
# Conçue pour Hugging Face Spaces (SDK Docker, port 7860), fonctionne aussi
# sur Railway/Fly/Render : docker build -t skyn . && docker run -p 7860:7860 skyn
#
# Étage 1 : build de l'application web Expo
FROM node:20-slim AS webbuild
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --ignore-scripts --no-audit --no-fund
COPY frontend/ .
# EXPO_PUBLIC_BACKEND_URL vide = API sur la même origine
ENV EXPO_PUBLIC_BACKEND_URL=""
RUN npx expo export --platform web

# Étage 2 : backend Python + modèles entraînés
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.local.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# SKYN Engine v2 (torch CPU) — SKYN_ML=0 pour une image légère sans ML
ARG SKYN_ML=1
COPY backend/requirements.ml.txt ./requirements.ml.txt
RUN if [ "$SKYN_ML" = "1" ]; then pip install --no-cache-dir -r requirements.ml.txt; fi

COPY backend/ .
RUN if [ "$SKYN_ML" = "1" ]; then python scripts/download_models.py; fi

# Application web construite à l'étage 1, servie par FastAPI sur /
COPY --from=webbuild /web/dist ./webapp

# Hugging Face Spaces exécute en utilisateur non-root (uid 1000)
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user
ENV HOME=/home/user

EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
