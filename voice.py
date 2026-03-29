"""
JARVIS Voice Module
-------------------
Handles:
  - Microphone recording (pyaudio, VAD-based silence detection)
  - Transcription (faster-whisper, local)
  - Text-to-speech (macOS AVSpeechSynthesizer via PyObjC)

Usage:
    from voice import VoiceIO
    v = VoiceIO()
    text = v.listen()          # record until silence, return transcript
    v.speak("Hello, Mason")    # speak aloud if TTS enabled
"""

import os
import wave
import tempfile
import threading
import subprocess
from pathlib import Path

# ── Config (falls back gracefully if dependencies missing) ────────────────────

SAMPLE_RATE    = 16000    # Hz — required by faster-whisper
CHANNELS       = 1
CHUNK          = 1024     # frames per buffer
SILENCE_LIMIT  = 1.5      # seconds of silence before stopping
SILENCE_THRESH = 500      # RMS threshold — tune if your mic is loud/quiet
MAX_RECORD_SEC = 60       # hard cutoff

try:
    import pyaudio
    PYAUDIO_OK = True
except ImportError:
    PYAUDIO_OK = False

try:
    from faster_whisper import WhisperModel
    WHISPER_OK = True
except ImportError:
    WHISPER_OK = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rms(data: bytes) -> float:
    """Root mean square of audio chunk — proxy for volume."""
    import array
    samples = array.array("h", data)
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


# ── VoiceIO class ─────────────────────────────────────────────────────────────

class VoiceIO:
    """
    Single entry point for voice I/O.
    Falls back gracefully: if faster-whisper isn't installed, listen() returns None.
    If TTS is disabled, speak() does nothing.
    """

    _whisper_model = None   # lazy-loaded, shared across instances
    _whisper_lock  = threading.Lock()

    def __init__(self, whisper_model: str = "base", tts_enabled: bool = True):
        self.tts_enabled   = tts_enabled
        self.whisper_model_name = whisper_model
        self._pa = None

    # ── Public API ────────────────────────────────────────────────────────────

    def listen(self) -> str | None:
        """
        Record from the microphone until silence, transcribe, return text.
        Returns None if recording or transcription fails.
        """
        if not PYAUDIO_OK:
            print("[Voice] pyaudio not installed — run: pip install pyaudio")
            return None
        if not WHISPER_OK:
            print("[Voice] faster-whisper not installed — run: pip install faster-whisper")
            return None

        audio_data = self._record()
        if not audio_data:
            return None

        wav_path = self._save_wav(audio_data)
        try:
            transcript = self._transcribe(wav_path)
            return transcript.strip() or None
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def speak(self, text: str):
        """
        Speak text via macOS AVSpeechSynthesizer.
        Non-blocking — runs in a background thread.
        Silently no-ops if TTS is disabled or PyObjC is unavailable.
        """
        if not self.tts_enabled:
            return
        threading.Thread(target=self._speak_blocking, args=(text,), daemon=True).start()

    def set_tts(self, enabled: bool):
        """Toggle TTS on/off at runtime."""
        self.tts_enabled = enabled

    # ── Recording ─────────────────────────────────────────────────────────────

    def _record(self) -> list[bytes] | None:
        """
        Record audio chunks until silence_limit of quiet.
        Returns list of raw PCM chunks.
        """
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

        print("[Voice] Listening...")
        frames = []
        silence_chunks = 0
        max_chunks = int(SAMPLE_RATE / CHUNK * MAX_RECORD_SEC)
        silence_chunks_needed = int(SAMPLE_RATE / CHUNK * SILENCE_LIMIT)
        started = False

        try:
            for _ in range(max_chunks):
                data = stream.read(CHUNK, exception_on_overflow=False)
                rms = _rms(data)

                if rms > SILENCE_THRESH:
                    started = True
                    silence_chunks = 0
                    frames.append(data)
                elif started:
                    frames.append(data)   # keep trailing silence for natural speech
                    silence_chunks += 1
                    if silence_chunks >= silence_chunks_needed:
                        break
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

        print(f"[Voice] Captured {len(frames)} chunks")
        return frames if frames else None

    def _save_wav(self, frames: list[bytes]) -> str:
        """Write PCM frames to a temp WAV file, return its path."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)   # paInt16 = 2 bytes
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b"".join(frames))
        return tmp.name

    # ── Transcription ─────────────────────────────────────────────────────────

    def _load_whisper(self):
        with VoiceIO._whisper_lock:
            if VoiceIO._whisper_model is None:
                print(f"[Voice] Loading Whisper '{self.whisper_model_name}'...")
                VoiceIO._whisper_model = WhisperModel(
                    self.whisper_model_name,
                    device="cpu",
                    compute_type="int8",
                )
                print("[Voice] Whisper ready")
        return VoiceIO._whisper_model

    def _transcribe(self, wav_path: str) -> str:
        model = self._load_whisper()
        segments, _ = model.transcribe(wav_path, beam_size=5, language="en")
        return " ".join(s.text for s in segments)

    # ── TTS ───────────────────────────────────────────────────────────────────

    def _speak_blocking(self, text: str):
        """Speak using macOS AVSpeechSynthesizer via PyObjC, fall back to 'say'."""
        try:
            self._speak_avsynth(text)
        except Exception:
            self._speak_say(text)

    def _speak_avsynth(self, text: str):
        """
        High-quality TTS via AVSpeechSynthesizer (PyObjC).
        Uses the system's default Siri/Enhanced voice.
        """
        try:
            from AVFoundation import (
                AVSpeechSynthesizer, AVSpeechUtterance, AVSpeechSynthesisVoice
            )
        except ImportError:
            raise RuntimeError("AVFoundation not available")

        import time

        synth    = AVSpeechSynthesizer.alloc().init()
        utt      = AVSpeechUtterance.speechUtteranceWithString_(text)
        utt.rate = 0.50       # 0.0 = very slow, 1.0 = very fast; 0.5 = natural
        utt.pitchMultiplier = 1.05

        # Pick best available voice — prefer enhanced/premium
        voices = AVSpeechSynthesisVoice.speechVoices()
        preferred = next(
            (v for v in voices
             if "en-US" in str(v.language())
             and ("enhanced" in str(v.name()).lower() or "premium" in str(v.name()).lower())),
            None
        )
        if preferred:
            utt.voice = preferred

        synth.speakUtterance_(utt)

        # Block until done
        while synth.isSpeaking():
            time.sleep(0.05)

    def _speak_say(self, text: str):
        """Fallback TTS using the 'say' command."""
        safe = text.replace('"', "'")
        subprocess.run(["say", "-r", "180", safe], timeout=120)


# ── Module-level convenience instance ─────────────────────────────────────────

_default_voice: VoiceIO | None = None

def get_voice(tts_enabled: bool = True) -> VoiceIO:
    """Return (or create) the module-level VoiceIO instance."""
    global _default_voice
    if _default_voice is None:
        from config.settings import VOICE_ENABLED, WHISPER_MODEL
        _default_voice = VoiceIO(
            whisper_model=WHISPER_MODEL,
            tts_enabled=VOICE_ENABLED and tts_enabled,
        )
    return _default_voice
