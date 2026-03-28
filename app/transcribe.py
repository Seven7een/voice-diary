"""Transcription backend interface and implementations.

Backends:
    - transcribe: AWS Transcribe Streaming (HTTP/2, no S3 needed)
    - whisper: Self-hosted faster-whisper (local CPU, fallback for AWS migration)

Selected via TRANSCRIPTION_BACKEND env var (default: transcribe).
"""

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

TRANSCRIPTION_BACKEND = os.environ.get("TRANSCRIPTION_BACKEND", "transcribe")


async def transcribe_audio(file_path: str) -> str | None:
    """Transcribe an audio file using the configured backend.

    Args:
        file_path: Path to the audio file on disk.

    Returns:
        Transcription text, or None if transcription fails.
    """
    backend = TRANSCRIPTION_BACKEND.lower().strip()

    if backend == "transcribe":
        return await _transcribe_aws(file_path)
    elif backend == "whisper":
        return await _transcribe_whisper(file_path)
    else:
        logger.error("Unknown transcription backend: %s", backend)
        return None


# ---------------------------------------------------------------------------
# AWS Transcribe Streaming
# ---------------------------------------------------------------------------
async def _transcribe_aws(file_path: str) -> str | None:
    """Transcribe audio via AWS Transcribe Streaming (HTTP/2).

    Uses the streaming API — audio bytes sent over HTTP/2 stream, text
    returned in real-time. No S3 bucket needed.

    Args:
        file_path: Path to the audio file.

    Returns:
        Transcription text, or None on failure.
    """
    try:
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler
        from amazon_transcribe.model import TranscriptEvent
    except ImportError:
        logger.error(
            "amazon-transcribe-streaming-sdk not installed. "
            "Install it or switch to TRANSCRIPTION_BACKEND=whisper"
        )
        return None

    path = Path(file_path)
    if not path.exists():
        logger.warning("Audio file not found: %s", file_path)
        return None

    # Detect format from magic bytes
    media_encoding, sample_rate = _detect_encoding(path)

    class ResultHandler(TranscriptResultStreamHandler):
        """Collect transcript results from the stream."""

        def __init__(self, stream):
            super().__init__(stream)
            self.transcripts: list[str] = []

        async def handle_transcript_event(self, transcript_event: TranscriptEvent):
            results = transcript_event.transcript.results
            for result in results:
                if not result.is_partial:
                    for alt in result.alternatives:
                        if alt.transcript:
                            self.transcripts.append(alt.transcript)

    try:
        client = TranscribeStreamingClient(region=os.environ.get("AWS_REGION", "us-east-1"))

        stream = await client.start_stream_transcription(
            language_code="en-US",
            media_sample_rate_hz=sample_rate,
            media_encoding=media_encoding,
        )

        # Send audio in chunks
        audio_bytes = path.read_bytes()
        chunk_size = 1024 * 16  # 16KB chunks
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            await stream.input_stream.send_audio_event(audio_chunk=chunk)
        await stream.input_stream.end_stream()

        # Collect results
        handler = ResultHandler(stream.output_stream)
        await handler.handle_events()

        transcript = " ".join(handler.transcripts).strip()
        if not transcript:
            logger.warning("Empty transcription from AWS Transcribe for %s", file_path)
            return None

        logger.info("AWS Transcribe: %s — %d chars", path.name, len(transcript))
        return transcript

    except Exception as e:
        logger.error("AWS Transcribe Streaming failed for %s: %s", file_path, e)
        return None


def _detect_encoding(path: Path) -> tuple[str, int]:
    """Detect audio encoding from magic bytes for AWS Transcribe.

    Args:
        path: Path to audio file.

    Returns:
        Tuple of (media_encoding, sample_rate_hz).
    """
    try:
        with open(path, "rb") as f:
            header = f.read(4)
    except OSError:
        return "ogg-opus", 48000  # safe default

    if header[:4] == b"\x1aE\xdf\xa3":  # WebM (EBML)
        return "ogg-opus", 48000  # Transcribe treats WebM/Opus as ogg-opus
    if header[:4] == b"OggS":
        return "ogg-opus", 48000
    if header[:4] == b"fLaC":
        return "flac", 16000

    return "ogg-opus", 48000


# ---------------------------------------------------------------------------
# Self-hosted Whisper (via faster-whisper)
# ---------------------------------------------------------------------------
_whisper_model = None


def _get_whisper():
    """Get or initialize the faster-whisper model (lazy singleton).

    Returns:
        faster_whisper.WhisperModel instance.
    """
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        model_name = os.environ.get("WHISPER_MODEL", "base")
        logger.info("Loading Whisper model: %s (cpu, int8)", model_name)
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        logger.info("Whisper model loaded.")
    return _whisper_model


async def _transcribe_whisper(file_path: str) -> str | None:
    """Transcribe audio via local faster-whisper (CPU).

    Args:
        file_path: Path to the audio file.

    Returns:
        Transcription text, or None on failure.
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("Audio file not found: %s", file_path)
        return None

    try:
        model = _get_whisper()
        segments, info = model.transcribe(str(path), beam_size=5)
        transcript = " ".join(seg.text.strip() for seg in segments)

        if not transcript.strip():
            logger.warning("Empty Whisper transcription for %s", file_path)
            return None

        logger.info(
            "Whisper: %s — %d chars, lang=%s (prob=%.2f)",
            path.name, len(transcript), info.language, info.language_probability,
        )
        return transcript
    except Exception as e:
        logger.error("Whisper transcription failed for %s: %s", file_path, e)
        return None
