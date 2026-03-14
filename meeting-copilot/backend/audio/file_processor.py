"""Audio file processor for batch processing of uploaded files."""

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from backend.audio.pipeline import AudioPipeline
from backend.config import Settings
from backend.storage.session import SessionStore
from backend.ws.protocol import TranscriptSegment

logger = logging.getLogger(__name__)


class FileAudioProcessor:
    """Processes audio files through the audio pipeline."""
    
    def __init__(self, settings: Settings, session_store: SessionStore):
        self.settings = settings
        self.session_store = session_store
        self._processing_tasks: dict[str, asyncio.Task] = {}
    
    async def process_file(
        self,
        file_path: Path,
        session_id: str,
        progress_callback: Optional[callable] = None
    ) -> dict:
        """Process an audio file and save results to session.
        
        Args:
            file_path: Path to audio file
            session_id: Session ID to save results to
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict with processing results
        """
        processing_id = str(uuid.uuid4())
        
        try:
            # Load and validate audio file
            audio_data, sample_rate = await self._load_audio_file(file_path)
            
            # Setup pipeline for this session
            pipeline = AudioPipeline(self.settings)
            
            # Create segment collector that saves to session
            segment_collector = SessionSegmentCollector(
                session_store, session_id, progress_callback
            )
            pipeline.on_segment(segment_collector.collect_segment)
            
            # Process audio in chunks
            await self._process_audio_chunks(pipeline, audio_data, sample_rate, progress_callback)
            
            # Flush remaining buffer
            await pipeline.reset()
            
            return {
                "processing_id": processing_id,
                "status": "completed",
                "segments_processed": segment_collector.segment_count,
                "duration_seconds": len(audio_data) / sample_rate
            }
            
        except Exception as e:
            logger.error(f"Audio file processing failed: {e}")
            return {
                "processing_id": processing_id,
                "status": "failed",
                "error": str(e)
            }
    
    async def _load_audio_file(self, file_path: Path) -> tuple[np.ndarray, int]:
        """Load and validate audio file."""
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")
        
        try:
            audio_data, sample_rate = sf.read(str(file_path))
            logger.info(f"Loaded audio: {len(audio_data)} samples at {sample_rate} Hz")
        except Exception as e:
            raise ValueError(f"Failed to load audio file: {e}")
        
        # Validate audio format
        if len(audio_data) == 0:
            raise ValueError("Audio file is empty")
        
        # Convert to mono if needed
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)
            logger.info("Converted stereo to mono")
        
        # Resample to 16kHz if needed
        if sample_rate != 16000:
            audio_data = self._resample_audio(audio_data, sample_rate, 16000)
            sample_rate = 16000
            logger.info("Resampled to 16kHz")
        
        return audio_data, sample_rate
    
    def _resample_audio(self, audio_data: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Resample audio data using linear interpolation."""
        ratio = to_rate / from_rate
        new_length = int(len(audio_data) * ratio)
        new_indices = np.linspace(0, len(audio_data) - 1, new_length)
        return np.interp(new_indices, np.arange(len(audio_data)), audio_data)
    
    async def _process_audio_chunks(
        self,
        pipeline: AudioPipeline,
        audio_data: np.ndarray,
        sample_rate: int,
        progress_callback: Optional[callable]
    ) -> None:
        """Process audio data in chunks to simulate real-time processing."""
        chunk_size = 4096  # Same as real-time processing
        total_chunks = (len(audio_data) + chunk_size - 1) // chunk_size
        
        # Convert to int16 PCM
        audio_int16 = (audio_data * 32767).astype(np.int16)
        
        for i in range(0, len(audio_int16), chunk_size):
            chunk = audio_int16[i:i + chunk_size]
            chunk_bytes = chunk.tobytes()
            
            await pipeline.process_audio_chunk(chunk_bytes)
            
            # Report progress
            if progress_callback:
                chunk_num = i // chunk_size + 1
                progress = min(chunk_num / total_chunks, 1.0)
                await progress_callback({
                    "type": "progress",
                    "progress": progress,
                    "current_chunk": chunk_num,
                    "total_chunks": total_chunks
                })
            
            # Small delay to prevent overwhelming the system
            await asyncio.sleep(0.01)


class SessionSegmentCollector:
    """Collects transcript segments and saves them to session storage."""
    
    def __init__(self, session_store: SessionStore, session_id: str, progress_callback: Optional[callable]):
        self.session_store = session_store
        self.session_id = session_id
        self.progress_callback = progress_callback
        self.segment_count = 0
    
    async def collect_segment(self, segment: TranscriptSegment) -> None:
        """Callback for audio pipeline segments."""
        await self.session_store.save_segment(self.session_id, segment)
        self.segment_count += 1
        
        # Report segment progress
        if self.progress_callback:
            await self.progress_callback({
                "type": "segment",
                "segment_count": self.segment_count,
                "segment": segment.model_dump()
            })
