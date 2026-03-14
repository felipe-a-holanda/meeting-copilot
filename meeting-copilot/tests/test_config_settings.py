"""Tests for Settings — Task 2.1: new audio capture fields."""
from __future__ import annotations

import os
import pytest

from backend.config import Settings


class TestSettingsDefaults:
    """Verify new fields have the correct default values."""

    def test_audio_capture_mode_default(self):
        s = Settings()
        assert s.audio_capture_mode == "backend"

    def test_recordings_dir_default(self):
        s = Settings()
        assert s.recordings_dir == "./recordings"

    def test_mic_volume_default(self):
        s = Settings()
        assert s.mic_volume == 2.0

    def test_default_mic_source_default(self):
        s = Settings()
        assert s.default_mic_source == ""

    def test_default_monitor_source_default(self):
        s = Settings()
        assert s.default_monitor_source == ""

    def test_save_recordings_default(self):
        s = Settings()
        assert s.save_recordings is True


class TestSettingsFromEnv:
    """Verify new fields can be overridden via environment variables."""

    def test_audio_capture_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("AUDIO_CAPTURE_MODE", "browser")
        s = Settings()
        assert s.audio_capture_mode == "browser"

    def test_recordings_dir_from_env(self, monkeypatch):
        monkeypatch.setenv("RECORDINGS_DIR", "/tmp/recordings")
        s = Settings()
        assert s.recordings_dir == "/tmp/recordings"

    def test_mic_volume_from_env(self, monkeypatch):
        monkeypatch.setenv("MIC_VOLUME", "3.5")
        s = Settings()
        assert s.mic_volume == pytest.approx(3.5)

    def test_default_mic_source_from_env(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_MIC_SOURCE", "alsa_input.pci-0000_00_1f.3.analog-stereo")
        s = Settings()
        assert s.default_mic_source == "alsa_input.pci-0000_00_1f.3.analog-stereo"

    def test_default_monitor_source_from_env(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_MONITOR_SOURCE", "alsa_output.pci.monitor")
        s = Settings()
        assert s.default_monitor_source == "alsa_output.pci.monitor"

    def test_save_recordings_false_from_env(self, monkeypatch):
        monkeypatch.setenv("SAVE_RECORDINGS", "false")
        s = Settings()
        assert s.save_recordings is False

    def test_audio_capture_mode_both(self, monkeypatch):
        monkeypatch.setenv("AUDIO_CAPTURE_MODE", "both")
        s = Settings()
        assert s.audio_capture_mode == "both"


class TestSettingsExistingFieldsUnchanged:
    """Ensure pre-existing fields still work correctly."""

    def test_whisper_model_field_exists(self):
        s = Settings()
        assert isinstance(s.whisper_model, str)
        assert s.whisper_model != ""

    def test_language_default(self):
        s = Settings()
        assert s.language == "pt"

    def test_summary_every_n_segments_default(self):
        s = Settings()
        assert s.summary_every_n_segments == 10

    def test_db_path_default(self):
        s = Settings()
        assert s.db_path == "meetings.db"
