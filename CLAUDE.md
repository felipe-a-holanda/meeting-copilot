# CLAUDE.md — Meeting Copilot Autonomous Build

## Who You Are

You are an autonomous coding agent building the **meeting-copilot** project from scratch. You work in a loop: read the task log, find the next unchecked task, implement it fully, test it, mark it done, and move on.

## Core Rules

1. **Always start by reading `TASK_LOG.md`** — find the first task marked `[ ]`
2. **Implement one task at a time** — do not skip ahead or batch multiple tasks
3. **Write real, working code** — no placeholders, no TODOs, no "implement later"
4. **Test before marking done** — run the code, verify it works, fix any errors
5. **After completing a task**, update `TASK_LOG.md`:
   - Change `[ ]` to `[x]`
   - Add a brief note of what you did under the task
   - Commit with message: `✅ Task X.Y: <description>`
6. **If a task fails or is blocked**, mark it `[!]` with a note explaining why, then move to the next task
7. **If all tasks are `[x]` or `[!]`**, output `🏁 ALL TASKS COMPLETE` and stop

## Project Context

You are building a real-time meeting copilot that:
- Captures audio from the browser via WebSocket
- Transcribes in real-time using faster-whisper (WhisperLiveKit)
- Identifies speakers via pyannote diarization
- Runs LLM reasoning (Ollama local, Claude API fallback) for:
  - Progressive summarization
  - Action item extraction
  - Contradiction detection
  - Reply suggestions
  - Custom user prompts
- Displays everything in a React frontend

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, WebSockets, Pydantic v2
- **Audio**: faster-whisper, WhisperLiveKit, pyannote.audio, Silero VAD
- **LLM**: Ollama (httpx calls to localhost:11434), Anthropic SDK (fallback)
- **Frontend**: React 18, TypeScript, Tailwind CSS
- **State**: SQLite via aiosqlite for session persistence

## Architecture Reference

Read `ARCHITECTURE.md` for the full system design, data models, prompt templates, and implementation details.

## Code Standards

- Use type hints everywhere in Python
- Use Pydantic models for all data structures
- Use async/await for all I/O operations
- Frontend: functional components with hooks, no class components
- Keep files focused — one class/concern per file
- Error handling: catch specific exceptions, log them, don't crash the server

## File Structure

All code goes in the `meeting-copilot/` directory:
- `backend/` — Python FastAPI application
- `frontend/` — React TypeScript application
- `scripts/` — Setup and utility scripts

## Testing Strategy

- Backend: use `pytest` with `pytest-asyncio` for async tests
- Test each module in isolation before integration
- For audio pipeline tests, use mock audio data (sine wave PCM)
- For LLM tests, mock the Ollama/Anthropic responses
- Frontend: basic smoke tests with component rendering
