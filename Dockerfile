# Deploiement SKYN sur Render (ou tout hebergeur Docker generique) — API +
# application web, dans une seule image.
#
# Reprend exactement la configuration deja validee par deploy_modal.py :
# memes bibliotheques systeme (libgl1, libglib2.0-0, requises par MediaPipe
# et OpenCV), meme requirements.local.txt (le jeu allege, sans les
# dependances LLM que le backend sait deja contourner si EMERGENT_LLM_KEY
# est absent), meme repertoire de sortie pour l'application web statique.
#
# Construction locale (verification avant push) :
#   docker build -t skyn .
#   docker run -p 8000:8000 -e SKYN_ALLOW_GUEST=1 skyn
#
# Sur Render : ce Dockerfile est detecte automatiquement via render.yaml
# (voir ce fichier pour le detail du service et des variables d'env).

# ── Etape 1 : build de l'application web (Expo -> export statique) ──
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
# scripts/ doit venir AVANT `npm ci`, pas apres : le hook `preinstall` du
# package.json execute `./scripts/check-pkg.js`, et sans ce fichier deja en
# place npm echoue en "not found" (code 127) avant meme de toucher au
# lockfile. Repere en reproduisant l'echec exact hors Docker (voir le
# commit qui a corrige ce Dockerfile pour le detail).
COPY frontend/package.json frontend/package-lock.json* ./
COPY frontend/scripts ./scripts
RUN npm ci
COPY frontend/ ./
RUN npx expo export --platform web

# ── Etape 2 : le serveur, avec l'app web deja construite montee dedans ──
FROM python:3.11-slim AS backend
WORKDIR /app

# MediaPipe et OpenCV en ont besoin au runtime, pas seulement au build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.local.txt ./requirements.local.txt
RUN pip install --no-cache-dir -r requirements.local.txt

COPY backend/ ./
# webapp/ est le repertoire par defaut lu par server.py (SKYN_WEB_DIR) : le
# placer la evite d'avoir a positionner cette variable en production.
COPY --from=frontend-build /app/frontend/dist ./webapp

# Render (comme la plupart des PaaS) fournit le port d'ecoute via $PORT ;
# 8000 est le repli pour une execution locale (docker run sans -e PORT=...).
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
