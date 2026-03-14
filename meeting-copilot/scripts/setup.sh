#!/usr/bin/env bash
# setup.sh — Automated setup for Meeting Copilot (local development)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Meeting Copilot Setup ==="
echo "Project root: $PROJECT_DIR"

# ── Python version check ──────────────────────────────────────────────────────
PYTHON=$(command -v python3.11 || command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.11+ is required but not found."
    exit 1
fi
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Using Python $PY_VERSION ($PYTHON)"

# ── Virtual environment ───────────────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi
source .venv/bin/activate
echo "Virtual environment: .venv"

# ── Python dependencies ───────────────────────────────────────────────────────
echo "Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet

# ── Environment file ──────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "  !! Edit .env to set ANTHROPIC_API_KEY and HF_TOKEN before running."
fi

# ── Node / frontend ───────────────────────────────────────────────────────────
if command -v node &>/dev/null; then
    NODE_VERSION=$(node --version)
    echo "Node $NODE_VERSION found — installing frontend dependencies..."
    cd frontend
    npm install --silent
    cd ..
else
    echo "WARNING: Node.js not found — skipping frontend setup."
    echo "  Install Node 18+ and run: cd frontend && npm install"
fi

# ── Ollama check ──────────────────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
    echo "Ollama found. Pulling default models (this may take a while)..."
    ollama pull llama3.1:8b || echo "WARNING: Could not pull llama3.1:8b"
else
    echo "WARNING: Ollama not found."
    echo "  Install from https://ollama.com and run:"
    echo "    ollama pull llama3.1:8b"
    echo "    ollama pull llama3.1:70b  # optional, for heavy reasoning"
fi

# ── Run backend tests ─────────────────────────────────────────────────────────
echo "Running backend tests..."
python -m pytest tests/ -q --tb=short 2>&1 | tail -5

echo ""
echo "=== Setup complete ==="
echo ""
echo "To start the backend:"
echo "  source .venv/bin/activate"
echo "  uvicorn backend.main:app --reload"
echo ""
echo "To start the frontend (separate terminal):"
echo "  cd frontend && npm start"
echo ""
echo "Backend API:  http://localhost:8000"
echo "Frontend:     http://localhost:3000"
