#!/usr/bin/env python3
"""
CLI tool for testing audio pipeline with audio files.

Usage:
    python -m backend.cli audio.wav --model turbo --language pt
    python -m backend.cli --mic --duration 30  # Record from microphone
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from backend.audio.pipeline import AudioPipeline
from backend.config import Settings
from backend.ws.protocol import TranscriptSegment

logger = logging.getLogger(__name__)


class CLITranscriptCollector:
    """Collect transcript segments for CLI output."""
    
    def __init__(self):
        self.segments = []
    
    async def collect_segment(self, segment: TranscriptSegment) -> None:
        """Callback for audio pipeline segments."""
        self.segments.append(segment)
        timestamp = f"{segment.timestamp_start:.1f}-{segment.timestamp_end:.1f}s"
        print(f"[{timestamp}] {segment.speaker}: {segment.text}")


async def process_audio_file(file_path: Path, settings: Settings) -> None:
    """Process an audio file through the pipeline."""
    if not file_path.exists():
        print(f"Error: File {file_path} not found")
        return
    
    print(f"Loading audio from {file_path}...")
    
    # Load audio file
    try:
        audio_data, sample_rate = sf.read(str(file_path))
        print(f"Loaded: {len(audio_data)} samples at {sample_rate} Hz")
    except Exception as e:
        print(f"Error loading audio file: {e}")
        return
    
    # Convert to mono and resample if needed
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)
    
    if sample_rate != 16000:
        # Simple resampling - in production use scipy.signal.resample
        import math
        ratio = 16000 / sample_rate
        new_length = int(len(audio_data) * ratio)
        audio_data = np.interp(
            np.linspace(0, len(audio_data), new_length),
            np.arange(len(audio_data)),
            audio_data
        )
        sample_rate = 16000
    
    # Convert to int16 PCM
    audio_int16 = (audio_data * 32767).astype(np.int16)
    
    # Setup pipeline
    collector = CLITranscriptCollector()
    pipeline = AudioPipeline(settings)
    pipeline.on_segment(collector.collect_segment)
    
    print("Starting transcription...")
    
    # Process in chunks (simulating real-time streaming)
    chunk_size = 4096  # Same as frontend
    for i in range(0, len(audio_int16), chunk_size):
        chunk = audio_int16[i:i + chunk_size]
        chunk_bytes = chunk.tobytes()
        await pipeline.process_audio_chunk(chunk_bytes)
        
        # Small delay to simulate real-time processing
        await asyncio.sleep(0.05)
    
    # Flush remaining buffer
    await pipeline.reset()
    
    print(f"\nTranscription complete! {len(collector.segments)} segments processed.")


async def record_from_microphone(duration: int, settings: Settings) -> None:
    """Record from microphone and process in real-time."""
    try:
        import pyaudio
    except ImportError:
        print("Error: pyaudio not installed. Install with:")
        print("  sudo apt-get install portaudio19-dev  # Ubuntu/Debian")
        print("  pip install pyaudio")
        return
    
    print(f"Recording for {duration} seconds...")
    
    # Audio parameters
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    CHUNK = 4096
    
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, 
                   input=True, frames_per_buffer=CHUNK)
    
    # Setup pipeline
    collector = CLITranscriptCollector()
    pipeline = AudioPipeline(settings)
    pipeline.on_segment(collector.collect_segment)
    
    print("Recording started. Speak now...")
    
    async def record_and_process():
        for _ in range(int(RATE / CHUNK * duration)):
            data = stream.read(CHUNK)
            await pipeline.process_audio_chunk(data)
            await asyncio.sleep(0.01)  # Small delay
    
    try:
        await record_and_process()
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        await pipeline.reset()
    
    print(f"\nRecording complete! {len(collector.segments)} segments processed.")


def main():
    parser = argparse.ArgumentParser(description="Test audio pipeline with audio files")
    parser.add_argument("input", nargs="?", help="Audio file path or --mic")
    parser.add_argument("--mic", action="store_true", help="Record from microphone")
    parser.add_argument("--duration", type=int, default=30, help="Recording duration in seconds")
    parser.add_argument("--model", default="turbo", help="Whisper model size")
    parser.add_argument("--language", default="pt", help="Language code")
    parser.add_argument("--diarization", action="store_true", help="Enable speaker diarization")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    # Setup settings
    settings = Settings()
    settings.whisper_model = args.model
    settings.language = args.language
    settings.enable_diarization = args.diarization
    
    async def run():
        if args.mic:
            await record_from_microphone(args.duration, settings)
        elif args.input:
            await process_audio_file(Path(args.input), settings)
        else:
            parser.print_help()
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
