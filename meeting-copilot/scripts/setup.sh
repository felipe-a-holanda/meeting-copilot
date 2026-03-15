#!/usr/bin/env bash
# setup.sh — Automated setup for Meeting Copilot (local development)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Meeting Copilot Setup ==="
echo "Project root: $PROJECT_DIR"

# ── System dependency checks ──────────────────────────────────────────────────
MISSING_DEPS=()

check_dep() {
    local cmd="$1" pkg="$2"
    if ! command -v "$cmd" &>/dev/null; then
        echo "  MISSING: $cmd (install: $pkg)"
        MISSING_DEPS+=("$cmd")
    else
        echo "  OK: $cmd ($(command -v "$cmd"))"
    fi
}

echo "Checking system dependencies for backend audio capture..."
check_dep pactl "sudo apt-get install pulseaudio-utils  # Ubuntu/Debian"
check_dep ffmpeg "sudo apt-get install ffmpeg           # Ubuntu/Debian"

if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
    echo ""
    echo "WARNING: The following system tools are required for backend audio capture:"
    for dep in "${MISSING_DEPS[@]}"; do
        case "$dep" in
            pactl)
                echo "  • pactl  — PulseAudio control tool"
                echo "    Ubuntu/Debian: sudo apt-get install pulseaudio-utils"
                echo "    Arch:          sudo pacman -S libpulse"
                echo "    Fedora:        sudo dnf install pulseaudio-utils"
                ;;
            ffmpeg)
                echo "  • ffmpeg — audio/video capture tool"
                echo "    Ubuntu/Debian: sudo apt-get install ffmpeg"
                echo "    Arch:          sudo pacman -S ffmpeg"
                echo "    Fedora:        sudo dnf install ffmpeg"
                ;;
        esac
    done
    echo ""
    echo "The application will still install, but recording will fail at runtime."
    echo "Install the above tools, then re-run this script (or start the server)."
    echo ""
else
    echo ""
    echo "Listing available PulseAudio sources (microphones + monitors):"
    pactl list sources short 2>/dev/null | awk '{printf "  %s\n", $2}' || echo "  (pactl list sources failed — PulseAudio may not be running)"
    echo ""
fi

# ── Python version check ──────────────────────────────────────────────────────
REQUIRED_MAJOR=3
REQUIRED_MINOR=11
PYENV_VERSION=${PYENV_VERSION:-3.11.9}
PYTHON=""

maybe_use_python() {
    local candidate="$1"
    [[ -z "$candidate" ]] && return 1
    if "$candidate" -c "import sys; sys.exit(0 if (sys.version_info.major, sys.version_info.minor) >= ($REQUIRED_MAJOR, $REQUIRED_MINOR) else 1)" &>/dev/null; then
        PYTHON="$candidate"
        return 0
    fi
    return 1
}

# Prefer an existing python3.11 binary if it actually works
maybe_use_python "$(command -v python3.11 2>/dev/null || true)" || true

# Fall back to pyenv if available (installs the requested version on first run)
if [[ -z "$PYTHON" ]] && command -v pyenv &>/dev/null; then
    if ! PYENV_VERSION="$PYENV_VERSION" pyenv prefix &>/dev/null; then
        echo "Python $PYENV_VERSION not installed in pyenv — installing (one-time setup)..."
        pyenv install "$PYENV_VERSION"
    fi
    PYENV_PYTHON=$(PYENV_VERSION="$PYENV_VERSION" pyenv which python3.11 2>/dev/null || true)
    maybe_use_python "$PYENV_PYTHON" || true
fi

# As a last resort, try whatever python3 points to (must still satisfy >=3.11)
if [[ -z "$PYTHON" ]]; then
    maybe_use_python "$(command -v python3 2>/dev/null || true)" || true
fi

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.11+ is required but not found."
    echo "If you use pyenv, run: pyenv install $PYENV_VERSION"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo "Using Python $PY_VERSION ($PYTHON)"

# ── Virtual environment ───────────────────────────────────────────────────────
if [[ -d ".venv" ]]; then
    if ! .venv/bin/python -c "import sys; sys.exit(0 if (sys.version_info.major, sys.version_info.minor) >= ($REQUIRED_MAJOR, $REQUIRED_MINOR) else 1)" &>/dev/null; then
        echo "Existing .venv uses an incompatible Python version — recreating..."
        rm -rf .venv
    else
        VENV_PY_VERSION=$(.venv/bin/python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        TARGET_PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if [[ "$VENV_PY_VERSION" != "$TARGET_PY_VERSION" ]]; then
            echo "Existing .venv targets Python $VENV_PY_VERSION but setup selected $TARGET_PY_VERSION — recreating..."
            rm -rf .venv
        fi
    fi
fi

if [[ ! -d ".venv" ]]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

source .venv/bin/activate
VENV_PYTHON="$(command -v python)"
echo "Virtual environment: .venv ($VENV_PYTHON)"

# ── Python dependencies ───────────────────────────────────────────────────────
echo "Installing Python dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet
"$VENV_PYTHON" -m pip install -e ".[dev]" --quiet

# ── Environment file ──────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "  !! Edit .env to set ANTHROPIC_API_KEY before running."
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
