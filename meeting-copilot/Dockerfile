# ── Stage 1: Build frontend ──────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Backend runtime ──────────────────────────────────────────────────
FROM python:3.11-slim

# System deps for audio processing (ffmpeg, libsndfile) and torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        websockets \
        "pydantic>=2.0" \
        "pydantic-settings>=2.0" \
        httpx \
        "faster-whisper>=1.0" \
        "anthropic>=0.40" \
        "aiosqlite>=0.20" \
        numpy

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend into static/ so FastAPI can serve it
COPY --from=frontend-builder /app/frontend/build ./static/

# Copy env example for reference
COPY .env.example ./

# Create directory for SQLite database
RUN mkdir -p /data

ENV DB_PATH=/data/meetings.db
ENV WS_HOST=0.0.0.0
ENV WS_PORT=8000

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
