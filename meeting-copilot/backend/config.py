from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Audio Pipeline
    whisper_model: str = "turbo"
    language: str = "pt"                     # Default language (set to "" for auto-detect)

    # Audio Capture (backend mode)
    audio_capture_mode: str = "backend"      # "backend" | "browser" | "both"
    recordings_dir: str = "./recordings"
    mic_volume: float = 2.0
    default_mic_source: str = ""             # Empty = auto-detect via pactl
    default_monitor_source: str = ""         # Empty = auto-detect via pactl
    save_recordings: bool = True

    # LLM - Local (Ollama)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"        # For summaries, action items
    ollama_heavy_model: str = "llama3.1:70b" # For contradictions, replies (optional)

    # LLM - API Fallback
    use_api_fallback: bool = False
    anthropic_api_key: str = ""              # Set via ANTHROPIC_API_KEY env var

    # Reasoning Triggers
    summary_every_n_segments: int = 10
    action_scan_every_n_segments: int = 5
    contradiction_check_seconds: int = 120

    # WebSocket / Server
    ws_host: str = "0.0.0.0"
    ws_port: int = 8000

    # Storage
    db_path: str = "meetings.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
