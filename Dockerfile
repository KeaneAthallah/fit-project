# --- frontend build -------------------------------------------------------
# Built in a separate stage so the final image keeps no Node runtime and no
# node_modules. The compiled dist/ is copied into the Python image, where
# app/dashboard/server.py serves it from the same origin as /api.
FROM node:22-slim AS frontend

WORKDIR /frontend

# Dependencies first: this layer is cached until the lockfile changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- runtime --------------------------------------------------------------
FROM python:3.11-slim

# System dependencies for OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ind \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Overwrite whatever host-side dist may have been copied in above.
COPY --from=frontend /frontend/dist ./frontend/dist

# Create runtime directories
RUN mkdir -p data logs output review database

ENV PYTHONUNBUFFERED=1

# Single-origin deployment: the API and the built SPA are both on port 8000.
EXPOSE 8000

CMD ["python", "main.py", "--help"]