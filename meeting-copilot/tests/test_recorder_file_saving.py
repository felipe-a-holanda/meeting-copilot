"""Tests for AudioRecorder optional WAV file saving (Tasks 1.4 / 1B.2)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.audio.recorder import AudioRecorder, RecordingStats


def _make_process_mock(returncode: int = 0):
    proc = MagicMock()
    proc.stdout = AsyncMock()
    proc.stdout.read = AsyncMock(return_value=b"")  # EOF immediately — prevents reader loop hang
    proc.stderr = AsyncMock()
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# _build_stream_cmd with file output
# ---------------------------------------------------------------------------


class TestBuildStreamCmdWithFile:
    def test_no_file_pipe_only(self):
        cmd = AudioRecorder._build_stream_cmd("my_source")
        assert "pipe:1" in cmd
        assert "pcm_s16le" not in cmd
        assert "-map" not in cmd

    def test_with_file_has_two_outputs(self):
        cmd = AudioRecorder._build_stream_cmd("my_source", file_path="/tmp/out.wav")
        assert "pipe:1" in cmd
        assert "/tmp/out.wav" in cmd
        assert "pcm_s16le" in cmd
        assert cmd.count("-map") == 2

    def test_with_file_correct_output_order(self):
        cmd = AudioRecorder._build_stream_cmd("my_source", file_path="/tmp/out.wav")
        pipe_idx = cmd.index("pipe:1")
        file_idx = cmd.index("/tmp/out.wav")
        assert pipe_idx < file_idx

    def test_with_file_sample_rate_and_channels(self):
        cmd = AudioRecorder._build_stream_cmd("my_source", file_path="/tmp/out.wav")
        ar_indices = [i for i, v in enumerate(cmd) if v == "-ar"]
        ac_indices = [i for i, v in enumerate(cmd) if v == "-ac"]
        # 2 outputs (pipe + file) = 2 -ar and 2 -ac
        assert len(ar_indices) == 2
        assert len(ac_indices) == 2
        assert all(cmd[i + 1] == "16000" for i in ar_indices)
        assert all(cmd[i + 1] == "1" for i in ac_indices)


# ---------------------------------------------------------------------------
# _make_recording_path
# ---------------------------------------------------------------------------


class TestMakeRecordingPath:
    def test_creates_directory(self, tmp_path):
        timestamp = "20260314_120000"
        meeting_dir, mic_filename, monitor_filename = AudioRecorder._make_recording_path(
            str(tmp_path), timestamp
        )
        assert meeting_dir.exists()
        assert meeting_dir.is_dir()

    def test_directory_structure(self, tmp_path):
        timestamp = "20260314_120000"
        meeting_dir, _, _ = AudioRecorder._make_recording_path(str(tmp_path), timestamp)
        assert meeting_dir == tmp_path / "20260314" / "meeting_20260314_120000"

    def test_mic_filename(self, tmp_path):
        timestamp = "20260314_120000"
        _, mic_filename, _ = AudioRecorder._make_recording_path(str(tmp_path), timestamp)
        assert mic_filename == "meeting_20260314_120000_mic.wav"

    def test_monitor_filename(self, tmp_path):
        timestamp = "20260314_120000"
        _, _, monitor_filename = AudioRecorder._make_recording_path(str(tmp_path), timestamp)
        assert monitor_filename == "meeting_20260314_120000_monitor.wav"

    def test_idempotent_on_existing_dir(self, tmp_path):
        timestamp = "20260314_120000"
        AudioRecorder._make_recording_path(str(tmp_path), timestamp)
        meeting_dir, _, _ = AudioRecorder._make_recording_path(str(tmp_path), timestamp)
        assert meeting_dir.exists()


# ---------------------------------------------------------------------------
# _write_metadata
# ---------------------------------------------------------------------------


class TestWriteMetadata:
    def test_creates_metadata_file(self, tmp_path):
        AudioRecorder._write_metadata(
            tmp_path, "Standup", "20260314_120000",
            ["meeting_20260314_120000_mic.wav", "meeting_20260314_120000_monitor.wav"],
        )
        metadata_file = tmp_path / "meeting_20260314_120000_metadata.json"
        assert metadata_file.exists()

    def test_metadata_content(self, tmp_path):
        audio_files = ["meeting_20260314_120000_mic.wav", "meeting_20260314_120000_monitor.wav"]
        AudioRecorder._write_metadata(tmp_path, "Standup", "20260314_120000", audio_files)
        metadata_file = tmp_path / "meeting_20260314_120000_metadata.json"
        data = json.loads(metadata_file.read_text())

        assert data["title"] == "Standup"
        assert data["timestamp"] == "20260314_120000"
        assert data["date"] == "20260314"
        assert data["audio_files"] == audio_files
        assert data["source"] == "local_recording"
        assert "T" in data["created_at"]
        assert "Z" in data["created_at"]

    def test_metadata_empty_title(self, tmp_path):
        AudioRecorder._write_metadata(tmp_path, "", "20260314_120000", ["mic.wav"])
        data = json.loads((tmp_path / "meeting_20260314_120000_metadata.json").read_text())
        assert data["title"] == ""

    def test_metadata_title_with_special_chars(self, tmp_path):
        title = 'Q1 "Planning" & Review'
        AudioRecorder._write_metadata(tmp_path, title, "20260314_120000", ["mic.wav"])
        data = json.loads((tmp_path / "meeting_20260314_120000_metadata.json").read_text())
        assert data["title"] == title

    def test_metadata_single_file_list(self, tmp_path):
        """Mic-only recording should have a single-element audio_files list."""
        AudioRecorder._write_metadata(
            tmp_path, "Solo", "20260314_120000",
            ["meeting_20260314_120000_mic.wav"],
        )
        data = json.loads((tmp_path / "meeting_20260314_120000_metadata.json").read_text())
        assert len(data["audio_files"]) == 1


# ---------------------------------------------------------------------------
# start() with save_to_file
# ---------------------------------------------------------------------------


class TestStartWithSaveToFile:
    @pytest.mark.asyncio
    async def test_start_save_false_no_file_output(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=False)
        for call_args in mock_exec.call_args_list:
            cmd = call_args[0]
            assert "pcm_s16le" not in cmd
        assert recorder._meeting_dir is None
        assert recorder._audio_files == []

    @pytest.mark.asyncio
    async def test_start_save_true_dual_stream_two_separate_wav_files(self, tmp_path):
        """Each stream gets its own ffmpeg call, each with a WAV file output."""
        recorder = AudioRecorder(recordings_dir=str(tmp_path))
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=True)

        assert mock_exec.call_count == 2
        # First call (mic): contains mic WAV
        mic_cmd = mock_exec.call_args_list[0][0]
        assert "pcm_s16le" in mic_cmd
        assert "pipe:1" in mic_cmd
        mic_wavs = [a for a in mic_cmd if isinstance(a, str) and a.endswith(".wav")]
        assert len(mic_wavs) == 1
        assert "_mic.wav" in mic_wavs[0]

        # Second call (monitor): contains monitor WAV
        mon_cmd = mock_exec.call_args_list[1][0]
        assert "pcm_s16le" in mon_cmd
        assert "pipe:1" in mon_cmd
        mon_wavs = [a for a in mon_cmd if isinstance(a, str) and a.endswith(".wav")]
        assert len(mon_wavs) == 1
        assert "_monitor.wav" in mon_wavs[0]

        assert len(recorder._audio_files) == 2

    @pytest.mark.asyncio
    async def test_start_save_true_creates_directory(self, tmp_path):
        recorder = AudioRecorder(recordings_dir=str(tmp_path))
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=True)
        assert recorder._meeting_dir is not None
        assert Path(recorder._meeting_dir).exists()

    @pytest.mark.asyncio
    async def test_start_stores_title(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon", title="My Meeting")
        assert recorder._title == "My Meeting"

    @pytest.mark.asyncio
    async def test_start_save_true_mic_only_one_file(self, tmp_path):
        """Mic-only fallback should save only mic.wav."""
        recorder = AudioRecorder(recordings_dir=str(tmp_path))
        mic_mock = _make_process_mock()
        with patch("asyncio.create_subprocess_exec", return_value=mic_mock) as mock_exec:
            await recorder.start(mic_source="mic", monitor_source="", save_to_file=True)
        assert mock_exec.call_count == 1
        mic_cmd = mock_exec.call_args_list[0][0]
        assert "pcm_s16le" in mic_cmd
        wav_args = [a for a in mic_cmd if isinstance(a, str) and a.endswith(".wav")]
        assert len(wav_args) == 1
        assert "_mic.wav" in wav_args[0]
        assert len(recorder._audio_files) == 1


# ---------------------------------------------------------------------------
# stop() with file saving
# ---------------------------------------------------------------------------


class TestStopWithFileSaving:
    @pytest.mark.asyncio
    async def test_stop_returns_audio_files_when_saving(self, tmp_path):
        recorder = AudioRecorder(recordings_dir=str(tmp_path))
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=True)
        stats = await recorder.stop()
        assert isinstance(stats, RecordingStats)
        assert len(stats.audio_files) == 2
        assert any("_mic.wav" in p for p in stats.audio_files)
        assert any("_monitor.wav" in p for p in stats.audio_files)

    @pytest.mark.asyncio
    async def test_stop_returns_file_path_as_meeting_dir(self, tmp_path):
        recorder = AudioRecorder(recordings_dir=str(tmp_path))
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=True)
        stats = await recorder.stop()
        assert stats.file_path is not None
        assert Path(stats.file_path).is_dir()

    @pytest.mark.asyncio
    async def test_stop_returns_empty_audio_files_when_not_saving(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=False)
        stats = await recorder.stop()
        assert stats.file_path is None
        assert stats.audio_files == []

    @pytest.mark.asyncio
    async def test_stop_writes_metadata_when_saving(self, tmp_path):
        recorder = AudioRecorder(recordings_dir=str(tmp_path))
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(
                mic_source="mic", monitor_source="mon",
                save_to_file=True, title="Sprint Review",
            )
        stats = await recorder.stop()
        meeting_dir = Path(stats.file_path)
        metadata_files = list(meeting_dir.glob("*_metadata.json"))
        assert len(metadata_files) == 1
        data = json.loads(metadata_files[0].read_text())
        assert data["title"] == "Sprint Review"
        assert data["source"] == "local_recording"
        assert len(data["audio_files"]) == 2

    @pytest.mark.asyncio
    async def test_stop_clears_state(self, tmp_path):
        recorder = AudioRecorder(recordings_dir=str(tmp_path))
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=True)
        await recorder.stop()
        assert recorder._meeting_dir is None
        assert recorder._audio_files == []
        assert recorder._title == ""

    @pytest.mark.asyncio
    async def test_stop_does_not_crash_if_metadata_write_fails(self):
        """Metadata write failure should be logged but not crash stop()."""
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon", save_to_file=False)
            # Force a bad state to trigger metadata failure
            recorder._meeting_dir = "/nonexistent_dir/that_cannot_exist"
            recorder._audio_files = ["/nonexistent_dir/that_cannot_exist/mic.wav"]
            recorder._timestamp = "20260314_120000"
        stats = await recorder.stop()
        assert stats is not None
