import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import requests
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()  # must run before any os.environ.get() calls below

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.config import AUDIENCES
from agent.graph import StoryState, graph
from agent.ingest import ingest_sources
from api.auth import router as auth_router
from api.deps import get_current_user
from db.database import AsyncSessionLocal, Base, engine, get_db
from db.models import Story, User, user_is_premium

logger = logging.getLogger(__name__)

DAILY_LIMIT   = int(os.environ.get("DAILY_LIMIT", "5"))
_ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")


def _require_admin(x_admin_secret: str = Header(default="")) -> None:
    if not _ADMIN_SECRET or x_admin_secret != _ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

_R2_ENDPOINT   = os.environ.get("R2_ENDPOINT", "")
_R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY", "")
_R2_SECRET_KEY = os.environ.get("R2_SECRET_KEY", "")
_R2_BUCKET     = os.environ.get("R2_BUCKET", "nightynight-audio")
_R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")


def _upload_to_r2(mp3_path: str, key: str) -> str | None:
    """Upload MP3 to Cloudflare R2, return public/presigned URL or None on failure."""
    if not _R2_ENDPOINT:
        return None
    try:
        import boto3
        client = boto3.client(
            "s3",
            endpoint_url=_R2_ENDPOINT,
            aws_access_key_id=_R2_ACCESS_KEY,
            aws_secret_access_key=_R2_SECRET_KEY,
            region_name="auto",
        )
        with open(mp3_path, "rb") as f:
            client.put_object(Bucket=_R2_BUCKET, Key=key, Body=f.read(), ContentType="audio/mpeg")
        if _R2_PUBLIC_URL:
            return f"{_R2_PUBLIC_URL}/{key}"
        # Fallback: presigned URL valid for 7 days (until public URL is configured)
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": _R2_BUCKET, "Key": key},
            ExpiresIn=7 * 24 * 3600,
        )
    except Exception as exc:
        logger.warning("R2 upload failed, falling back to local: %s", exc)
        return None

# Sources directory is at the repo root: CountingStars/sources/
_SOURCES_DIR = str(Path(__file__).resolve().parents[3] / "sources")

# Ambient sounds directory: CountingStars/sounds/ (or override via SOUNDS_DIR env var)
_SOUNDS_DIR = os.environ.get("SOUNDS_DIR", str(Path(__file__).resolve().parents[3] / "sounds"))


_agent_logger = logging.getLogger("agent")
_agent_logger.setLevel(logging.INFO)
if not _agent_logger.handlers:
    _agent_logger.addHandler(logging.StreamHandler())

# ── App setup ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified.")
    yield
    await engine.dispose()

app = FastAPI(title="CountingStars API", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router)

_FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[_FRONTEND_ORIGIN, "http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Audio files served here (populated in Phase 2 when TTS is added)
AUDIO_DIR = os.environ.get("AUDIO_DIR", "/tmp/counting_stars_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")
os.makedirs(_SOUNDS_DIR, exist_ok=True)
app.mount("/sounds", StaticFiles(directory=_SOUNDS_DIR), name="sounds")


# ── TTS helpers ───────────────────────────────────────────────────────────────

def _prepare_tts_text(text: str) -> str:
    """Strip formatting that causes ElevenLabs to shift vocal energy mid-story.

    LLMs sometimes ignore "no headers" instructions. Any structural marker
    (Chapter headings, markdown bold, horizontal rules) makes ElevenLabs switch
    to an "announcement" voice that spikes in volume/energy.
    """
    # Markdown bold / italic
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_\n]+)_{1,3}', r'\1', text)
    # ATX headings (# Title)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Horizontal rules (--- / *** / ___)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Explicit chapter/part/section labels the LLM might still emit
    text = re.sub(
        r'^(chapter|part|section|act)\s+[\w\d]+[:\s\-–—]*.*$',
        '',
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    # Collapse 3+ blank lines down to one paragraph break
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


_HEADING_RE = re.compile(r'^\s*(#{1,3}\s+.+|[A-Z][A-Z\s\d:,\-]{10,})\s*$', re.MULTILINE)

def _split_into_chapter_segments(text: str, n_chapters: int) -> list[str]:
    """Split story text into n_chapters paragraph-proportional segments.

    Stories are plain prose (no chapter headings per prompt rules), so we split
    by distributing paragraphs as evenly as possible across the chapter count.
    """
    if n_chapters <= 1 or not text.strip():
        return [_prepare_tts_text(text)]

    clean = _prepare_tts_text(text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()]
    n = min(n_chapters, len(paragraphs))
    if n <= 1:
        return [clean]
    base, remainder = divmod(len(paragraphs), n)
    result, idx = [], 0
    for i in range(n):
        size = base + (1 if i < remainder else 0)
        result.append("\n\n".join(paragraphs[idx: idx + size]))
        idx += size
    return result


def _chunk_text(text: str, max_chars: int = 4000) -> list[tuple[str, bool]]:
    """Split text into (chunk, is_chapter_boundary) tuples.

    Strategy:
      1. Split on chapter/section headings first — these are natural hard breaks.
      2. Within each section, split on blank-line paragraph boundaries.
      3. Only sentence-split a paragraph that exceeds max_chars.

    Returns a list of (text_chunk, is_chapter_boundary) where is_chapter_boundary=True
    marks the *start* of a new chapter (used to insert longer silence before it).
    """

    def _sentences(para: str) -> list[str]:
        """Split a paragraph into sentences as a fallback for long paragraphs."""
        sents = re.split(r'(?<=[.!?。！？])\s+', para)
        chunks: list[str] = []
        cur = ""
        for s in sents:
            if len(s) > max_chars:
                if cur:
                    chunks.append(cur.strip())
                    cur = ""
                for i in range(0, len(s), max_chars):
                    chunks.append(s[i : i + max_chars])
                continue
            if len(cur) + len(s) + 1 > max_chars:
                if cur:
                    chunks.append(cur.strip())
                cur = s
            else:
                cur += (" " if cur else "") + s
        if cur:
            chunks.append(cur.strip())
        return [c for c in chunks if c]

    # Split into sections on heading boundaries
    sections: list[tuple[str, bool]] = []  # (text, is_chapter_start)
    last_end = 0
    is_first = True
    for m in _HEADING_RE.finditer(text):
        preceding = text[last_end : m.start()].strip()
        if preceding:
            sections.append((preceding, False))
        heading = m.group(0).strip()
        # Combine heading with the text that follows until next heading
        # (we'll handle that below)
        sections.append((heading, not is_first))
        is_first = False
        last_end = m.end()
    tail = text[last_end:].strip()
    if tail:
        sections.append((tail, False))

    if not sections:
        sections = [(text, False)]

    result: list[tuple[str, bool]] = []
    for section_text, is_chapter in sections:
        # Split section into paragraphs
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', section_text) if p.strip()]
        if not paragraphs:
            continue
        first_para = True
        for para in paragraphs:
            mark_chapter = is_chapter and first_para
            first_para = False
            if len(para) <= max_chars:
                result.append((para, mark_chapter))
            else:
                # Sentence-level fallback
                sents = _sentences(para)
                for j, s in enumerate(sents):
                    result.append((s, mark_chapter and j == 0))
    return [(c, b) for c, b in result if c]


_AMBIENT_MANIFEST: dict[str, list[str]] = {
    "cosmos": [
        "cosmos01.wav", "cosmos02.wav", "cosmos03.wav",
        "cosmos04.wav", "cosmos05.wav",
    ],
    "fire": [
        "LightFire01.mp3", "fire01.mp3", "fire02.mp3",
        "fire03.mp3", "fire04.mp3", "fire05.mp3",
    ],
    "ocean": ["ocean01.mp3"],
    "rain": [
        "Light rain recordings mixed settings-01.wav",
        "Light rain recordings mixed settings-02.wav",
        "Light rain recordings mixed settings-03.wav",
        "Light rain recordings mixed settings-04.wav",
        "Light rain recordings mixed settings-05.wav",
        "Light rain recordings mixed settings-06.wav",
    ],
    "woods": ["woods01.mp3", "woods02.mp3", "woods03.mp3"],
}


def _pick_ambient_url(ambient: str) -> str | None:
    """Return a URL for a random ambient file in the given category.

    Prefers the R2 public URL when configured; falls back to the local
    /sounds StaticFiles mount for local development.
    """
    files = _AMBIENT_MANIFEST.get(ambient)
    if not files:
        return None
    filename = random.choice(files)
    if _R2_PUBLIC_URL:
        return f"{_R2_PUBLIC_URL}/sounds/{ambient}/{quote(filename)}"
    return f"/sounds/{ambient}/{quote(filename)}"


_ELEVENLABS_TTS_URL  = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_ELEVENLABS_MAX_CHARS = 39_000  # ElevenLabs hard limit per request

# Curated ElevenLabs voices for bedtime narration.
# Keys are the friendly names shown in the UI; values are stable voice IDs.
ELEVENLABS_VOICES: dict[str, str] = {
    # ── User's own voices (work on free plan) ────────────────────────────────
    "True Crime & Horror Narrator":          "tZssYepgGaQmegsMEXjK",
    "Kyle Manning":                          "q8hD3YAFEqLvfbspywun",
    "Archer (deep, steady, relaxing)":       "X0K9Z1Bor9SpbE1wSaoe",
    "Adam Stone (smooth, deep, relaxed)":    "NFG5qt843uXKj4pFvR7C",
    "Christopher (gentle, trustworthy)":     "G17SuINrv2H9FC6nvetn",
    "John Doe (deep)":                       "EiNlNiXeDU1pqqOPrYMO",
    "Autumn Veil (warm, reflective female)": "KoVIHoyLDrQyd4pGalbs",
    # ── ElevenLabs library voices (require paid plan) ────────────────────────
    "Rachel (warm female)":                  "21m00Tcm4TlvDq8ikWAM",
    "Aria (calm female)":                    "9BWtsMINqrJLrRacOk9x",
    "Adam (deep male)":                      "pNInz6obpgDQGcFmaJgB",
    "Eric (calm male)":                      "cjVigY5qzO86Huf0OWal",
    "Charlotte (soft female)":               "XB0fDUnXU5powFXDhCwa",
    "Daniel (narrative male)":               "onwK4e9ZLuTAKqWW03F9",
}


_AUDIENCE_SPEED: dict[str, float] = {
    "children (ages 4–6)":  0.70,
    "children (ages 7–12)": 0.75,
    "children (ages 13+)":  0.80,
}
_DEFAULT_SPEED = 0.80


def _synthesize_chunk(idx: int, chunk: str, voice_id: str, api_key: str, speed: float = _DEFAULT_SPEED) -> tuple[int, bytes]:
    """Call ElevenLabs TTS and return raw MP3 bytes."""
    url = _ELEVENLABS_TTS_URL.format(voice_id=voice_id)
    payload = {
        "text": chunk,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability": 0.88,
            "similarity_boost": 0.80,
            "style": 0.05,
            "use_speaker_boost": True,
            "speed": speed,
        },
    }

    resp = requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        params={"output_format": "mp3_44100_128"},
        timeout=300,
    )

    if not resp.ok:
        raise RuntimeError(
            f"ElevenLabs TTS error {resp.status_code}: {resp.text[:400]}"
        )

    return idx, resp.content


def _synthesize_blocking(
    story_text: str,
    voice_name: str,
    out_path: str,
    audience: str = "",
    num_chapters: int = 1,
) -> tuple[int, int]:
    """Synthesize story text to MP3. Ambient sound is played client-side.

    Single-chunk path (common case): writes raw ElevenLabs bytes directly to disk
    — no pydub, no PCM decode, negligible memory.
    Multi-chunk path: concatenates raw MP3 bytes in order. No pydub needed.

    Returns (duration_ms, chunks_synthesized).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    speed = _AUDIENCE_SPEED.get(audience, _DEFAULT_SPEED)

    if num_chapters > 1:
        segments = [s.strip() for s in _split_into_chapter_segments(story_text, num_chapters) if s.strip()]
        if len(segments) > 1:
            tts_text = ' <break time="2.5s" /> '.join(segments)
        else:
            tts_text = _prepare_tts_text(story_text)
    else:
        tts_text = _prepare_tts_text(story_text)

    # Send as one request when under ElevenLabs' 40k-char limit (the normal case).
    # Raw-byte concatenation of multiple MP3s produces broken duration metadata in browsers.
    if len(tts_text) <= _ELEVENLABS_MAX_CHARS:
        chunk_tuples = [(tts_text, False)]
    else:
        chunk_tuples = _chunk_text(tts_text, max_chars=_ELEVENLABS_MAX_CHARS)
    logger.info("TTS: synthesizing %d chunk(s) (speed=%.2f, chapters=%d)", len(chunk_tuples), speed, num_chapters)

    raw_results: dict[int, bytes] = {}
    with ThreadPoolExecutor(max_workers=min(len(chunk_tuples), 2)) as pool:
        futures = {
            pool.submit(_synthesize_chunk, i, text, voice_name, api_key, speed): i
            for i, (text, _) in enumerate(chunk_tuples)
        }
        for future in as_completed(futures):
            idx, raw = future.result()
            raw_results[idx] = raw
            logger.info("TTS: chunk %d/%d done (%d KB)", idx + 1, len(chunk_tuples), len(raw) // 1024)

    # Concatenate chunks in order and write to disk — no pydub, no PCM in memory.
    with open(out_path, "wb") as f:
        for i in range(len(chunk_tuples)):
            f.write(raw_results[i])

    total_bytes = sum(len(b) for b in raw_results.values())
    duration_ms = total_bytes * 1000 // 16000  # rough estimate at 128 kbps
    return duration_ms, len(chunk_tuples)


# ── Inworld TTS ───────────────────────────────────────────────────────────────

_INWORLD_TTS_URL      = "https://api.inworld.ai/tts/v1/voice:stream"
_INWORLD_MAX_CHARS    = 1_800   # hard limit 2000; 200 char safety margin
_INWORLD_API_KEY      = os.environ.get("INWORLD_API_KEY", "")
_INWORLD_DEFAULT_VOICE = "Blake"

INWORLD_VOICES: dict[str, str] = {
    "Blake (warm, intimate male)":    "Blake",
    "Craig (refined British male)":   "Craig",
    "Clive (calm, British male)":     "Clive",
}


def _inworld_chunk_bytes(text: str, voice_id: str, api_key: str, speed: float = _DEFAULT_SPEED) -> bytes:
    """Synthesize one chunk (≤1800 chars) via Inworld, return raw MP3 bytes."""
    if not api_key:
        raise RuntimeError("INWORLD_API_KEY is missing")
    if len(text) > _INWORLD_MAX_CHARS:
        raise ValueError(f"Inworld chunk too long: {len(text)} chars")

    resp = requests.post(
        _INWORLD_TTS_URL,
        headers={
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "text":        text,
            "voiceId":     voice_id,
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": speed},
            "modelId":     "inworld-tts-1.5-max",
        },
        stream=True,
        timeout=120,
    )
    resp.raise_for_status()

    parts: list[bytes] = []
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        data = json.loads(line)
        result = data.get("result") or {}
        b64 = (
            result.get("audioContent")
            or result.get("audio")
            or data.get("audioContent")
            or data.get("audio")
        )
        if b64:
            parts.append(base64.b64decode(b64))

    if not parts:
        raise RuntimeError("Inworld returned no audio chunks")
    return b"".join(parts)


def _synthesize_inworld_blocking(
    story_text: str,
    voice_name: str,
    out_path: str,
    audience: str = "",
    num_chapters: int = 1,
) -> tuple[int, int]:
    """Inworld TTS: clean → chunk → synthesize sequentially → write single MP3.

    Same signature as _synthesize_blocking so the call site swap is minimal.
    Returns (duration_ms_estimate, chunks_synthesized).
    """
    _valid_inworld = set(INWORLD_VOICES.values())
    voice_id = voice_name if voice_name in _valid_inworld else _INWORLD_DEFAULT_VOICE
    speed    = _AUDIENCE_SPEED.get(audience, _DEFAULT_SPEED)

    # Clean FIRST, then chunk — avoids chunk boundaries landing inside markdown artifacts
    tts_text = _prepare_tts_text(story_text)
    chunks   = _chunk_text(tts_text, max_chars=_INWORLD_MAX_CHARS)

    logger.info("Inworld TTS: synthesizing %d chunk(s) (speed=%.2f)", len(chunks), speed)
    all_bytes: list[bytes] = []
    for i, (chunk_text, _) in enumerate(chunks):
        audio = _inworld_chunk_bytes(chunk_text, voice_id, _INWORLD_API_KEY, speed)
        all_bytes.append(audio)
        logger.info("Inworld TTS: chunk %d/%d done (%d KB)", i + 1, len(chunks), len(audio) // 1024)

    with open(out_path, "wb") as f:
        f.write(b"".join(all_bytes))

    words       = len(tts_text.split())
    duration_ms = int(words / 160 * 60_000)  # ~160 WPM at Inworld default speed
    return duration_ms, len(chunks)


# ── Auth / usage helpers ──────────────────────────────────────────────────────

async def _check_limit_or_raise(user_id: str) -> None:
    """Read-only pre-flight check — gives a clean 429 before streaming starts.

    Does not increment counters; the atomic increment happens later inside
    _reserve_and_save_story once the story text is ready.
    """
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        today = date.today()
        daily = user.daily_count if user.daily_reset_at >= today else 0
        if daily >= DAILY_LIMIT:
            raise HTTPException(status_code=429, detail="Daily limit reached")


async def _reserve_and_save_story(
    user_id: str, topic: str, story_text: str, duration_min: int,
) -> str:
    """Atomically increment quota counters and persist the generated story text.

    Combining these two writes in one transaction ensures a quota slot is never
    consumed without a corresponding story record — if either write fails, both
    roll back together.

    Returns the new story's UUID so audio_url can be patched in later via
    _update_story_audio once synthesis completes.
    Raises HTTP 429 if the limit was reached by a concurrent request.
    """
    async with AsyncSessionLocal() as db:
        async with db.begin():
            stmt = select(User).where(User.id == user_id).with_for_update()
            locked = (await db.execute(stmt)).scalar_one()

            today = date.today()
            if locked.daily_reset_at < today:
                locked.daily_count = 0
                locked.daily_reset_at = today
            if locked.monthly_reset_at < today.replace(day=1):
                locked.monthly_count = 0
                locked.monthly_reset_at = today.replace(day=1)

            if locked.daily_count >= DAILY_LIMIT:
                raise HTTPException(status_code=429, detail="Daily limit reached")
            locked.daily_count  += 1
            locked.monthly_count += 1

            story = Story(
                user_id=user_id,
                topic=topic,
                story_text=story_text,
                audio_url=None,
                duration_min=duration_min,
            )
            db.add(story)
            await db.flush()   # assigns story.id within the transaction
            return str(story.id)


async def _update_story_audio(story_id: str, audio_url: str) -> None:
    """Patch audio_url onto an existing story row after synthesis completes."""
    async with AsyncSessionLocal() as db:
        async with db.begin():
            story = (await db.execute(
                select(Story).where(Story.id == story_id)
            )).scalar_one_or_none()
            if story:
                story.audio_url = audio_url


# ── Request / response models ─────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200, description="Story topic")
    duration_min: int = Field(default=15, ge=8, le=25, description="Target duration in minutes (8–25)")
    style: str = Field(default="calm documentary", max_length=100)
    audience: str = Field(default="curious adults", max_length=100)
    domain: str = Field(default="general science", max_length=100)
    voice: str = Field(default="21m00Tcm4TlvDq8ikWAM", description="ElevenLabs voice ID")

    @field_validator("audience")
    @classmethod
    def audience_must_be_valid(cls, v: str) -> str:
        if v not in AUDIENCES:
            raise ValueError(f"audience must be one of: {AUDIENCES}")
        return v


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _initial_story_state(request: "GenerateRequest") -> StoryState:
    """Translate a GenerateRequest into the required StoryState fields for the graph."""
    return {
        "topic":        request.topic,
        "duration_min": request.duration_min,
        "style":        request.style,
        "audience":     request.audience,
        "domain":       request.domain,
        "tts_speed":    _AUDIENCE_SPEED.get(request.audience, _DEFAULT_SPEED),
    }


def _sse(payload: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# Node names that represent meaningful user-facing progress steps.
# Nodes not in this set (e.g. routing helpers) are ignored in the stream.
_PROGRESS_NODES = {
    "plan_story",
    "write_chapter",
    "assemble_chapters",
    "polish_story",
}


def _audio_content_hash(text: str, is_premium: bool) -> str:
    """Stable cache key for a (tier, text) pair — first 16 hex chars of SHA-256."""
    tier = "premium" if is_premium else "free"
    return hashlib.sha256(f"{tier}:{text}".encode()).hexdigest()[:16]


def _audio_local_path(content_hash: str) -> str:
    return os.path.join(AUDIO_DIR, f"{content_hash}.mp3")


def _finalize_audio(content_hash: str) -> str:
    """Upload local MP3 to R2 and return the public URL (blocking).

    Falls back to the local /audio/ mount when R2 is not configured (dev).
    """
    local_path = _audio_local_path(content_hash)
    r2_url = _upload_to_r2(local_path, f"{content_hash}.mp3")
    url = r2_url or f"/audio/{content_hash}.mp3"
    logger.info("TTS complete. audio_url=%s", url)
    return url


def _run_tts(
    text: str,
    voice: str,
    out_path: str,
    audience: str,
    num_chapters: int,
    is_premium: bool,
) -> tuple[int, int]:
    """Blocking TTS dispatch: ElevenLabs for premium users, Inworld for free."""
    if is_premium:
        logger.info("[tts] provider=elevenlabs voice=%s", voice)
        return _synthesize_blocking(text, voice, out_path, audience, num_chapters)
    logger.info("[tts] provider=inworld voice=%s", voice)
    return _synthesize_inworld_blocking(text, voice, out_path, audience, num_chapters)


async def _stream_graph(request: GenerateRequest, user_id: str | None = None, is_premium: bool = False) -> AsyncIterator[str]:
    """Run the LangGraph graph and yield SSE events at each node completion.

    stream_mode="updates" yields only the fields changed by each node, not the
    full state. We therefore maintain current_state ourselves, merging every
    update into it so we always have the complete picture when building events.

    TTS synthesis is kicked off as a background executor task the moment
    polish_story finishes (final text is ready then), so it runs in parallel
    with the SSE delivery and Streamlit re-render rather than waiting for a
    second client request.
    """

    initial_state = _initial_story_state(request)

    # Seed current_state with the inputs; nodes will fill in the rest.
    current_state: dict = dict(initial_state)

    synthesis_future = None
    content_hash: str | None = None
    story_id: str | None = None

    try:
        async for chunk in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_updates in chunk.items():
                # node_updates is only the delta — merge it into the full state
                if isinstance(node_updates, dict):
                    current_state.update(node_updates)

                # polish_story just finished — final_story is ready. Kick off TTS now
                # so synthesis runs in parallel with SSE delivery + Streamlit re-render.
                if node_name == "polish_story" and synthesis_future is None:
                    polished = current_state.get("final_story")
                    if polished:
                        content_hash = _audio_content_hash(polished, is_premium)
                        audio_out = _audio_local_path(content_hash)
                        if not os.path.exists(audio_out):
                            loop = asyncio.get_running_loop()
                            synthesis_future = loop.run_in_executor(
                                None, _run_tts,
                                polished, request.voice, audio_out, request.audience,
                                current_state.get("num_chapters", 1), is_premium,
                            )
                        else:
                            logger.info("TTS cache hit — skipping synthesis.")
                        if user_id:
                            try:
                                story_id = await _reserve_and_save_story(
                                    user_id, request.topic, polished, request.duration_min
                                )
                            except Exception as exc:
                                logger.warning("Failed to reserve story slot: %s", exc)
                                raise

                if node_name not in _PROGRESS_NODES:
                    continue

                # chapter_index is set per-Send during parallel writes
                chapter_idx = current_state.get("chapter_index")
                chapter_num = chapter_idx + 1 if isinstance(chapter_idx, int) else None

                yield _sse({
                    "event": "node_done",
                    "node": node_name,
                    "chapter": chapter_num,
                    "message": current_state.get("status_message", ""),
                })

        # Graph complete — await TTS (may already be done by now)
        final_story = current_state.get("final_story")
        audio_url:  str | None = None
        tts_error:  str | None = None

        if synthesis_future is not None:
            try:
                # Send keepalive comments while TTS is running so the proxy
                # doesn't close the SSE connection during a long synthesis.
                while not synthesis_future.done():
                    yield ": tts-pending\n\n"
                    await asyncio.sleep(5)
                await synthesis_future
                audio_url = await asyncio.get_running_loop().run_in_executor(
                    None, _finalize_audio, content_hash
                )
            except Exception as exc:
                logger.error("Background TTS synthesis failed: %s", exc)
                tts_error = str(exc)
        elif content_hash and os.path.exists(_audio_local_path(content_hash)):
            audio_url = f"/audio/{content_hash}.mp3"

        if final_story:
            if story_id and audio_url:
                try:
                    await _update_story_audio(story_id, audio_url)
                except Exception as exc:
                    logger.warning("Failed to update story audio_url: %s", exc)
            yield _sse({
                "event": "done",
                "final_story": final_story,
                "audio_url": audio_url,
                "tts_error": tts_error,
            })
        else:
            yield _sse({"event": "error", "message": "Graph completed but final_story is missing."})

    except ValueError as exc:
        # Structured errors from _parse_chapter_plans or prompt validation
        yield _sse({"event": "error", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        yield _sse({"event": "error", "message": f"Unexpected error: {exc}"})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/config")
async def config() -> dict:
    """Return server-side configuration the frontend needs to stay in sync. No auth required."""
    return {
        "audiences":          AUDIENCES,
        "ambient_categories": list(_AMBIENT_MANIFEST.keys()),
    }


@app.get("/voices")
async def voices() -> dict:
    """Return the voice catalog grouped by tier. No auth required."""
    return {
        "free": [
            {"label": label, "id": voice_id}
            for label, voice_id in INWORLD_VOICES.items()
        ],
        "premium": [
            {"label": label, "id": voice_id}
            for label, voice_id in ELEVENLABS_VOICES.items()
        ],
    }


@app.get("/ambient/{category}")
async def ambient_random(category: str):
    """Redirect to a random ambient audio file for the given category.

    Serves from Cloudflare R2 (when R2_PUBLIC_URL is set) or the local
    /sounds StaticFiles mount as a fallback for local development.
    """
    url = _pick_ambient_url(category)
    if not url:
        raise HTTPException(status_code=404, detail=f"No audio files found for category: {category}")
    return RedirectResponse(url=url, status_code=302)


@app.post("/index")
async def index(drop_old: bool = False, _: None = Depends(_require_admin)) -> JSONResponse:
    """Scan sources/ PDFs and (re-)index them into Milvus.

    Pass ?drop_old=true to wipe the collection and rebuild from scratch.
    Safe to call again to add newly added PDFs without wiping existing data.
    """
    if not Path(_SOURCES_DIR).is_dir():
        raise HTTPException(status_code=500, detail=f"sources dir not found: {_SOURCES_DIR}")
    try:
        summary = ingest_sources(_SOURCES_DIR, drop_old=drop_old)
        return JSONResponse(content={"status": "ok", **summary})
    except Exception as exc:
        logger.error("/index failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/generate")
async def generate(
    request: GenerateRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Generate a bedtime science story and stream progress via Server-Sent Events.

    Requires a valid Bearer token. Usage is checked and reserved before streaming
    starts so a 429 is returned as a proper HTTP response, not an SSE error event.

    - `node_done`  — a LangGraph node finished; includes `node`, `chapter`, `message`
    - `done`       — pipeline complete; includes `final_story` and `audio_url`
    - `error`      — something went wrong; includes `message`
    """
    await _check_limit_or_raise(str(current_user.id))
    return StreamingResponse(
        _stream_graph(request, str(current_user.id), user_is_premium(current_user)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
