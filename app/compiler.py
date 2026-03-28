"""Diary compiler — transcribes recordings and compiles diary entries.

Pipeline:
    1. Audio → transcription (AWS Transcribe Streaming or Whisper, configurable)
    2. Text transcripts → Bedrock Claude → diary entry
"""

import json
import logging
import os
from datetime import date
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select, cast, Date, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Recording, DiaryEntry
from app.transcribe import transcribe_audio, TRANSCRIPTION_BACKEND

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# Bedrock (text-only — diary compilation)
# ---------------------------------------------------------------------------
def _get_bedrock_client():
    """Create a Bedrock Runtime client using env-var credentials."""
    return boto3.client(
        "bedrock-runtime",
        region_name=AWS_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def _invoke_bedrock(client, messages: list[dict], system: str | None = None) -> str:
    """Invoke Claude via Bedrock invoke_model (Messages API, text only).

    Args:
        client: Bedrock Runtime client.
        messages: List of message dicts in Claude Messages API format.
        system: Optional system prompt.

    Returns:
        The text content from Claude's response.

    Raises:
        RuntimeError: If the API call fails.
    """
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 8192,
        "messages": messages,
    }
    if system:
        body["system"] = system

    try:
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        result = json.loads(response["body"].read())
        text_parts = [b["text"] for b in result.get("content", []) if b.get("type") == "text"]
        return "\n".join(text_parts)
    except (BotoCoreError, ClientError) as e:
        logger.error("Bedrock API call failed: %s", e)
        raise RuntimeError(f"Bedrock API call failed: {e}") from e


# ---------------------------------------------------------------------------
# Diary compilation pipeline
# ---------------------------------------------------------------------------
async def compile_diary_entry(target_date: date, force: bool = False) -> DiaryEntry | None:
    """Compile all uncompiled recordings for a date into a diary entry.

    Pipeline:
    1. Gather uncompiled recordings for the date (or ALL if force=True)
    2. Transcribe each via configured backend (AWS Transcribe or Whisper)
    3. Compile transcriptions into a diary entry via Bedrock Claude (text only)
    4. Store the entry and mark recordings as compiled

    Args:
        target_date: The date to compile.
        force: If True, delete existing entry and recompile ALL recordings.

    Returns:
        The created DiaryEntry, or None if compilation fails or no recordings found.
    """
    async with async_session() as db:
        # Check if entry already exists
        existing = await db.execute(
            select(DiaryEntry).where(DiaryEntry.entry_date == target_date)
        )
        existing_entry = existing.scalar_one_or_none()

        if existing_entry and not force:
            logger.info("Diary entry already exists for %s, skipping.", target_date)
            return None

        if existing_entry and force:
            logger.info("Force recompile: deleting existing entry for %s", target_date)
            await db.delete(existing_entry)
            # Reset ALL recordings for this date
            all_recs_stmt = (
                select(Recording)
                .where(cast(Recording.recorded_at, Date) == target_date)
            )
            all_recs_result = await db.execute(all_recs_stmt)
            for rec in all_recs_result.scalars().all():
                rec.compiled = False
                rec.transcript = None
            await db.flush()

        # Gather recordings — all of them (force resets compiled flag above)
        stmt = (
            select(Recording)
            .where(
                and_(
                    cast(Recording.recorded_at, Date) == target_date,
                    Recording.compiled == False,  # noqa: E712
                )
            )
            .order_by(Recording.recorded_at.asc())
        )
        result = await db.execute(stmt)
        recordings = result.scalars().all()

        if not recordings:
            logger.info("No uncompiled recordings for %s", target_date)
            return None

        logger.info(
            "Compiling diary entry for %s — %d recordings (backend=%s)",
            target_date, len(recordings), TRANSCRIPTION_BACKEND,
        )

        # Step 1: Transcribe each recording
        transcriptions: list[dict] = []

        for i, rec in enumerate(recordings):
            logger.info(
                "Transcribing recording %d/%d (%s)", i + 1, len(recordings), rec.id
            )
            transcript = await transcribe_audio(rec.file_path)
            if transcript:
                transcriptions.append({
                    "time": rec.recorded_at.strftime("%H:%M"),
                    "transcript": transcript,
                    "duration_seconds": rec.duration_seconds,
                })
                # Store individual transcript on the recording
                rec.transcript = transcript

        if not transcriptions:
            logger.warning("All transcriptions failed for %s", target_date)
            return None

        # Step 2: Compile transcriptions into diary entry via Bedrock Claude
        logger.info("Compiling %d transcriptions into diary entry via Bedrock...", len(transcriptions))

        transcription_text = "\n\n".join(
            f"**[{t['time']}]** ({t['duration_seconds'] or '?'}s)\n{t['transcript']}"
            for t in transcriptions
        )

        compile_messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Date: {target_date.strftime('%A, %B %d, %Y')}\n\n"
                            f"Transcriptions:\n\n{transcription_text}"
                        ),
                    }
                ],
            }
        ]

        system_prompt = (
            "You are writing a personal diary entry. Given these voice note "
            "transcriptions from throughout the day (with timestamps), compile "
            "them into a cohesive diary entry in markdown format. Preserve the "
            "speaker's voice and natural style. Include time references naturally. "
            "Keep it authentic — genuine personal reflection, not polished prose. "
            "If only one recording exists, still write a brief entry capturing "
            "what was said."
        )

        client = _get_bedrock_client()
        try:
            diary_content = _invoke_bedrock(client, compile_messages, system=system_prompt)
        except RuntimeError:
            logger.error("Failed to compile diary entry for %s", target_date)
            return None

        # Calculate totals
        total_duration = sum(
            r.duration_seconds for r in recordings if r.duration_seconds
        )

        # Create diary entry
        entry = DiaryEntry(
            entry_date=target_date,
            content=diary_content,
            recording_count=len(recordings),
            total_duration_seconds=total_duration,
            model_used=f"{TRANSCRIPTION_BACKEND}+bedrock:{BEDROCK_MODEL_ID}",
        )
        db.add(entry)

        # Mark all recordings as compiled
        for rec in recordings:
            rec.compiled = True

        await db.commit()
        await db.refresh(entry)

        logger.info(
            "Diary entry compiled for %s — %d recordings, %d chars",
            target_date, len(recordings), len(diary_content),
        )
        return entry
