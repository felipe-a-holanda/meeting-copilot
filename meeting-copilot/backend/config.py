from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Audio Pipeline
    whisper_model: str = "turbo"
    language: str = "pt"                     # Default language (set to "" for auto-detect)
    enable_diarization: bool = False

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

    # HuggingFace (needed for pyannote diarization models)
    hf_token: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
