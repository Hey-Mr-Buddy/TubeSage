import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeRequestFailed,
)

from app.config import get_settings
from app.schemas import ChapterMarker, TranscriptSnippet

logger = logging.getLogger("tubesage.youtube")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHAPTER_LINE_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s+[-–—]?\s*(.+)", re.MULTILINE
)


class VideoInputError(ValueError):
    pass


class TranscriptUnavailable(RuntimeError):
    pass


def parse_video_id(value: str) -> str:
    value = value.strip()
    if VIDEO_ID_RE.fullmatch(value):
        return value
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise VideoInputError("Enter a valid YouTube video URL.") from exc
    host = (parsed.hostname or "").lower().removeprefix("www.")
    video_id = ""
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            video_id = parsed.path.split("/")[2]
    elif host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise VideoInputError("That does not look like a valid YouTube video link or ID.")
    return video_id


def extract_chapters_from_description(description: str) -> List[ChapterMarker]:
    """Parse native YouTube chapters from text descriptions formatted with timestamps."""
    if not description:
        return []
    chapters: List[ChapterMarker] = []
    for match in CHAPTER_LINE_RE.finditer(description):
        hours, minutes, seconds, title = match.groups()
        h = int(hours) if hours else 0
        m = int(minutes)
        s = int(seconds)
        total_seconds = h * 3600 + m * 60 + s
        clean_title = title.strip().strip("[]()-–— ")
        if clean_title:
            chapters.append(ChapterMarker(title=clean_title, start_seconds=float(total_seconds)))

    # Compute end_seconds sequentially
    for i in range(len(chapters) - 1):
        chapters[i].end_seconds = chapters[i + 1].start_seconds
    return chapters


def get_metadata(video_id: str) -> Tuple[str, List[ChapterMarker]]:
    """Fetch video metadata and native chapters from oEmbed and public page headers."""
    title = f"YouTube video {video_id}"
    chapters: List[ChapterMarker] = []
    try:
        response = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=12,
        )
        if response.status_code == 200:
            title = (response.json().get("title") or title)[:300]
    except Exception as exc:
        logger.warning("Could not fetch oEmbed metadata for %s: %s", video_id, exc)

    # Attempt to fetch page description for chapters
    try:
        page_resp = httpx.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10,
        )
        if page_resp.status_code == 200:
            chapters = extract_chapters_from_description(page_resp.text)
    except Exception as exc:
        logger.debug("Failed extracting native chapters from HTML: %s", exc)

    return title, chapters


def get_video_info(video_id: str) -> dict:
    """Read public title/duration metadata for preflight plan enforcement."""
    title = f"YouTube video {video_id}"
    duration = None
    try:
        response = httpx.get(f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if response.status_code == 200:
            title_match = re.search(r'<meta name="title" content="([^"]+)', response.text)
            if title_match:
                title = title_match.group(1)
            length = re.search(r'"lengthSeconds":"(\d+)"', response.text)
            if length:
                duration = int(length.group(1))
    except Exception as exc:
        logger.info("Video preflight metadata unavailable for %s: %s", video_id, exc)
    return {"video_id": video_id, "title": title, "duration_seconds": duration}


def whisper_stt_fallback(video_id: str) -> Tuple[List[TranscriptSnippet], str]:
    """
    Tier-3 Audio Ingestion Fallback:
    Invoked when YouTube manual and auto-generated captions are absent or blocked.
    Downloads the audio stream via yt-dlp and runs local Whisper / faster-whisper STT.
    """
    logger.info("Triggering Whisper STT fallback pipeline for video %s", video_id)
    # Check if faster_whisper or whisper is installed in the runtime
    try:
        import yt_dlp
        from faster_whisper import WhisperModel
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = os.path.join(tmp_dir, f"{video_id}.mp3")
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(tmp_dir, f"{video_id}.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

            # Use faster-whisper base.en for sub-minute transcription latency
            model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments, info = model.transcribe(audio_path, beam_size=3)

            snippets = []
            for seg in segments:
                text = seg.text.strip()
                if text:
                    snippets.append(
                        TranscriptSnippet(
                            start_seconds=float(seg.start),
                            end_seconds=float(seg.end),
                            text=text,
                        )
                    )
            return snippets, "en (Whisper STT)"
    except ImportError:
        logger.warning("Local faster-whisper or yt-dlp not available in environment.")
        raise TranscriptUnavailable(
            "YouTube captions were disabled or unavailable, and local Whisper STT engine is not installed. "
            "Please install yt-dlp and faster-whisper or use a video with native captions enabled."
        )
    except Exception as exc:
        logger.error("Whisper STT transcription failed for %s: %s", video_id, exc)
        raise TranscriptUnavailable(
            f"Whisper STT transcription failed for video: {str(exc)}"
        ) from exc


def fetch_transcript_resilient(
    video_id: str,
) -> Tuple[List[TranscriptSnippet], str, bool]:
    """
    Resilient Multi-Modal Ingestion Hierarchy:
      1. Manual Captions (highest quality, exact casing/punctuation)
      2. Auto-generated Captions (YouTube ASR fallback)
      3. Whisper STT Fallback (audio stream download + neural STT)
    """
    languages = get_settings().language_list
    transcript_track = None
    is_generated = False
    language_code = "en"

    # Tier 1 & 2: Query YouTube Transcript API
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        # 1. First search specifically for MANUAL transcripts
        try:
            transcript_track = transcript_list.find_manually_created_transcript(languages)
            is_generated = False
            logger.info("Found manual captions for video %s", video_id)
        except Exception:
            logger.info("Manual captions not found; checking auto-generated for %s", video_id)

        # 2. Fall back to auto-generated transcripts
        if transcript_track is None:
            try:
                transcript_track = transcript_list.find_generated_transcript(languages)
                is_generated = True
                logger.info("Found auto-generated captions for video %s", video_id)
            except Exception:
                logger.info("No auto-generated captions in preferred languages for %s", video_id)

        # 3. Fallback to any transcript track found
        if transcript_track is None:
            transcript_track = transcript_list.find_transcript(languages)
            is_generated = transcript_track.is_generated

    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, AgeRestricted, YouTubeRequestFailed, Exception) as exc:
        logger.warning(
            "YouTube transcript API failed for %s (%s). Attempting Tier-3 Whisper STT fallback.",
            video_id,
            type(exc).__name__,
        )
        try:
            snippets, lang = whisper_stt_fallback(video_id)
            return snippets, lang, True
        except TranscriptUnavailable:
            raise
        except Exception as fallback_exc:
            raise TranscriptUnavailable(
                "Could not retrieve captions from YouTube or Whisper STT. "
                "The video may be private, age-restricted, or temporarily rate-limited."
            ) from fallback_exc

    try:
        raw_items = transcript_track.fetch().to_raw_data()
        language_code = transcript_track.language_code
    except Exception as exc:
        logger.warning("Failed fetching raw caption data for %s: %s", video_id, exc)
        return whisper_stt_fallback(video_id)[0], "en (Whisper STT)", True

    # Preprocessing & sentence boundary alignment
    snippets: List[TranscriptSnippet] = []
    for item in raw_items:
        clean_text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
        start = max(0.0, float(item.get("start", 0)))
        duration = max(0.0, float(item.get("duration", 0)))
        if clean_text:
            snippets.append(
                TranscriptSnippet(
                    start_seconds=start,
                    end_seconds=start + duration,
                    text=clean_text,
                )
            )

    if not snippets:
        raise TranscriptUnavailable("The retrieved caption track was empty.")

    total_duration = max(item.end_seconds for item in snippets)
    settings = get_settings()
    max_allowed = (1440 if settings.cloud_mode else settings.max_video_minutes) * 60
    if total_duration > max_allowed:
        raise TranscriptUnavailable(
            f"This video ({round(total_duration / 60, 1)}m) exceeds the configured limit of {get_settings().max_video_minutes} minutes."
        )

    return snippets, language_code, is_generated
