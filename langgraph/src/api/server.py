import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.graph import StoryState, graph, ingest_sources

logger = logging.getLogger(__name__)

# Sources directory is at the repo root: CountingStars/sources/
_SOURCES_DIR = str(Path(__file__).resolve().parents[3] / "sources")

# Ambient sounds directory: CountingStars/sounds/ (or override via SOUNDS_DIR env var)
_SOUNDS_DIR = os.environ.get("SOUNDS_DIR", str(Path(__file__).resolve().parents[3] / "sounds"))

# One representative file per ambient category
_AMBIENT_FILES: dict[str, str] = {
    "fire":   "fire/fire01.mp3",
    "rain":   "rain/Light rain recordings mixed settings-01.wav",
    "ocean":  "ocean/ocean01.mp3",
    "woods":  "woods/woods01.mp3",
    "cosmos": "cosmos/cosmos01.wav",
}

# rag_domain → ambient mapping used when ambient == "auto"
_DOMAIN_AMBIENT: dict[str, str] = {
    "cosmos":       "cosmos",
    "life":         "woods",
    "civilization": "fire",
}
_DEFAULT_AMBIENT = "rain"


def _resolve_ambient(ambient: str, domain: str) -> str:
    """Return resolved ambient name. If 'auto', pick from rag_domain; else use as-is."""
    if ambient != "auto":
        return ambient
    return _DOMAIN_AMBIENT.get(domain.lower(), _DEFAULT_AMBIENT)

load_dotenv()

_agent_logger = logging.getLogger("agent")
_agent_logger.setLevel(logging.INFO)
if not _agent_logger.handlers:
    _agent_logger.addHandler(logging.StreamHandler())

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="CountingStars API", version="0.1.0")


@app.on_event("startup")
async def auto_index_on_startup() -> None:
    """Index sources/ into Milvus on first boot if the collection doesn't exist yet.

    Uses utility.has_collection() as the authoritative check — no false negatives
    from empty search results. Restarts are instant if the collection already exists.
    To force a full rebuild, call POST /index?drop_old=true manually.
    """
    from pymilvus import connections, utility
    from agent.graph import _MILVUS_URI, _MILVUS_TOKEN, _MILVUS_COLLECTION

    if not Path(_SOURCES_DIR).is_dir():
        logger.warning("sources dir not found at %s — skipping auto-index", _SOURCES_DIR)
        return

    try:
        connections.connect(uri=_MILVUS_URI, token=_MILVUS_TOKEN or None)
        if utility.has_collection(_MILVUS_COLLECTION):
            logger.info("Milvus collection '%s' already exists — skipping auto-index.", _MILVUS_COLLECTION)
            # Warm up the vector store cache here (async context) so verify_facts
            # doesn't trigger AsyncMilvusClient warnings on its first sync call.
            from agent.graph import _get_vector_store
            _get_vector_store()
            return
    except Exception as exc:
        logger.warning("Could not reach Milvus (%s) — skipping auto-index.", exc)
        return

    logger.info("Collection not found — starting auto-index...")
    try:
        summary = ingest_sources(_SOURCES_DIR, drop_old=False)
        logger.info("Auto-index complete: %s", summary)
    except Exception as exc:
        logger.error("Auto-index failed (server will still start): %s", exc)
        return

    # Warm up the cached vector store here (async context) so the first call
    # from verify_facts (sync node) doesn't trigger the AsyncMilvusClient warning.
    from agent.graph import _get_vector_store
    _get_vector_store()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
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


def _chunk_text(text: str, max_chars: int = 4000) -> list[tuple[str, bool]]:
    """Split text into (chunk, is_chapter_boundary) tuples.

    Strategy:
      1. Split on chapter/section headings first — these are natural hard breaks.
      2. Within each section, split on blank-line paragraph boundaries.
      3. Only sentence-split a paragraph that exceeds max_chars.

    Returns a list of (text_chunk, is_chapter_boundary) where is_chapter_boundary=True
    marks the *start* of a new chapter (used to insert longer silence before it).
    """
    # Detect chapter headings: lines that start with #, or ALL-CAPS titles, etc.
    _HEADING_RE = re.compile(r'^\s*(#{1,3}\s+.+|[A-Z][A-Z\s\d:,\-]{10,})\s*$', re.MULTILINE)

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


def _pick_ambient_file(ambient: str) -> str | None:
    """Return a random audio file from the ambient subfolder, or None if not found."""
    import random

    subfolder = Path(_SOUNDS_DIR) / ambient
    if not subfolder.is_dir():
        return None
    files = [
        f for f in subfolder.iterdir()
        if f.suffix.lower() in (".mp3", ".wav", ".ogg", ".flac")
    ]
    return str(random.choice(files)) if files else None


_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

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
    "children (ages 4–6)":  0.74,
    "children (ages 7–12)": 0.79,
    "children (ages 13+)":  0.83,
}
_DEFAULT_SPEED = 0.88


def _synthesize_chunk(idx: int, chunk: str, voice_id: str, api_key: str, speed: float = _DEFAULT_SPEED) -> tuple[int, bytes]:
    """Call ElevenLabs TTS and return raw MP3 bytes."""
    import requests

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
    ambient: str,
    ambient_db: float,
    out_path: str,
    audience: str = "",
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
    chunk_tuples = _chunk_text(_prepare_tts_text(story_text), max_chars=39000)
    logger.info("TTS: synthesizing %d chunk(s) (speed=%.2f)", len(chunk_tuples), speed)

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


# ── Request / response models ─────────────────────────────────────────────────

class AudioRequest(BaseModel):
    story_text: str = Field(..., min_length=100, description="The final story text to convert to audio")
    voice: str = Field(
        default="21m00Tcm4TlvDq8ikWAM",
        description=(
            "ElevenLabs voice ID. "
            "Rachel (warm female): '21m00Tcm4TlvDq8ikWAM'. "
            "Adam (deep male): 'pNInz6obpgDQGcFmaJgB'. "
            "Daniel (narrative male): 'onwK4e9ZLuTAKqWW03F9'."
        ),
    )
    ambient: str = Field(
        default="none",
        description='Ambient sound: "fire", "rain", "ocean", "woods", or "none"',
    )
    ambient_db: float = Field(
        default=-12.0,
        ge=-40.0,
        le=-6.0,
        description="Ambient volume relative to narration in dB (negative = quieter)",
    )


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200, description="Story topic")
    duration_min: int = Field(
        default=15,
        ge=8,
        le=25,
        description="Target episode duration in minutes (8–25)",
    )
    style: str = Field(
        default="calm documentary",
        max_length=100,
        description='Narration style, e.g. "calm documentary", "gentle bedtime"',
    )
    audience: str = Field(
        default="curious adults",
        max_length=100,
        description='Target audience, e.g. "curious adults", "science enthusiasts"',
    )
    domain: str = Field(
        default="general science",
        max_length=100,
        description='Science domain, e.g. "cosmology", "biology", "history of science"',
    )
    # TTS fields — server kicks off synthesis immediately after polish_story completes
    voice: str = Field(
        default="21m00Tcm4TlvDq8ikWAM",
        description=(
            "ElevenLabs voice ID. "
            "Rachel (warm female): '21m00Tcm4TlvDq8ikWAM'. "
            "Adam (deep male): 'pNInz6obpgDQGcFmaJgB'. "
            "Daniel (narrative male): 'onwK4e9ZLuTAKqWW03F9'."
        ),
    )
    ambient: str = Field(
        default="auto",
        description='"auto" picks ambient by domain; or "fire","rain","ocean","woods","cosmos","none"',
    )
    ambient_db: float = Field(default=-12.0, ge=-40.0, le=-6.0)


# ── SSE helpers ───────────────────────────────────────────────────────────────

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


async def _stream_graph(request: GenerateRequest) -> AsyncIterator[str]:
    """Run the LangGraph graph and yield SSE events at each node completion.

    stream_mode="updates" yields only the fields changed by each node, not the
    full state. We therefore maintain current_state ourselves, merging every
    update into it so we always have the complete picture when building events.

    TTS synthesis is kicked off as a background executor task the moment
    polish_story finishes (final text is ready then), so it runs in parallel
    with the SSE delivery and Streamlit re-render rather than waiting for a
    second client request.
    """

    initial_state: StoryState = {
        "topic": request.topic,
        "duration_min": request.duration_min,
        "style": request.style,
        "audience": request.audience,
        "domain": request.domain,
    }

    # Seed current_state with the inputs; nodes will fill in the rest.
    current_state: dict = dict(initial_state)

    synthesis_future = None
    content_hash: str | None = None

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
                        resolved_ambient = _resolve_ambient(request.ambient, request.domain)
                        content_hash = hashlib.sha256(polished.encode()).hexdigest()[:16]
                        audio_out = os.path.join(AUDIO_DIR, f"{content_hash}.mp3")
                        if not os.path.exists(audio_out):
                            loop = asyncio.get_event_loop()
                            synthesis_future = loop.run_in_executor(
                                None, _synthesize_blocking,
                                polished, request.voice, resolved_ambient,
                                request.ambient_db, audio_out, request.audience,
                            )
                            logger.info("TTS synthesis started in background (parallel chunks).")
                        else:
                            logger.info("TTS cache hit — skipping synthesis.")

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
                    "forced_chapters": [],
                })

        # Graph complete — await TTS (may already be done by now)
        final_story = current_state.get("final_story")
        audio_url: str | None = None

        if synthesis_future is not None:
            try:
                # Send keepalive comments while TTS is running so the proxy
                # doesn't close the SSE connection during a long synthesis.
                while not synthesis_future.done():
                    yield ": tts-pending\n\n"
                    await asyncio.sleep(5)
                await synthesis_future
                audio_url = f"/audio/{content_hash}.mp3"
                logger.info("TTS synthesis complete.")
            except Exception as exc:
                logger.error("Background TTS synthesis failed: %s", exc)
        elif content_hash and os.path.exists(os.path.join(AUDIO_DIR, f"{content_hash}.mp3")):
            audio_url = f"/audio/{content_hash}.mp3"

        if final_story:
            yield _sse({
                "event": "done",
                "final_story": final_story,
                "audio_url": audio_url,
                "forced_chapters": [],
                "status_message": current_state.get("status_message", ""),
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


@app.get("/ambient/{category}")
async def ambient_random(category: str):
    """Redirect to a random audio file from the given ambient category folder.

    Uses RedirectResponse → /sounds/... so the StaticFiles mount handles the
    actual file transfer, including Range requests (needed for audio seeking).
    """
    file_path = _pick_ambient_file(category)
    if not file_path:
        raise HTTPException(status_code=404, detail=f"No audio files found for category: {category}")
    rel = Path(file_path).relative_to(Path(_SOUNDS_DIR))
    return RedirectResponse(url=f"/sounds/{rel}", status_code=302)


@app.post("/index")
async def index(drop_old: bool = False) -> JSONResponse:
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


@app.post("/generate-audio")
async def generate_audio(request: AudioRequest) -> JSONResponse:
    """Convert story text to audio via Gemini TTS, optionally mixed with ambient sound.

    Long stories are split into sentence-boundary chunks (≤4000 chars each) and
    synthesized in sequence, then concatenated with pydub. Audio is cached by content
    hash — repeated calls for the same story return instantly without re-synthesizing.

    Returns JSON: { audio_url, duration_seconds, chunks_synthesized, ambient_mixed }
    """
    # Stable filename from content hash — free deduplication
    content_hash = hashlib.sha256(request.story_text.encode()).hexdigest()[:16]
    audio_filename = f"{content_hash}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)

    if os.path.exists(audio_path):
        return JSONResponse(content={
            "audio_url": f"/audio/{audio_filename}",
            "duration_seconds": 0,
            "chunks_synthesized": 0,
            "ambient_mixed": request.ambient,
            "cached": True,
        })

    try:
        loop = asyncio.get_event_loop()
        duration_ms, chunks_synthesized = await loop.run_in_executor(
            None,
            _synthesize_blocking,
            request.story_text,
            request.voice,
            request.ambient,
            request.ambient_db,
            audio_path,
        )
    except Exception as exc:
        logger.error("/generate-audio failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return JSONResponse(content={
        "audio_url": f"/audio/{audio_filename}",
        "duration_seconds": duration_ms // 1000,
        "chunks_synthesized": chunks_synthesized,
        "ambient_mixed": request.ambient,
        "cached": False,
    })


@app.post("/generate")
async def generate(request: GenerateRequest) -> StreamingResponse:
    """
    Generate a bedtime science story and stream progress via Server-Sent Events.

    The client should open an EventSource (or use fetch with stream=true) and
    listen for `data:` lines. Each line is a JSON object with an `event` field:

    - `node_done`  — a LangGraph node finished; includes `node`, `chapter`, `message`
    - `done`       — pipeline complete; includes `final_story` and `forced_chapters`
    - `error`      — something went wrong; includes `message`
    """
    return StreamingResponse(
        _stream_graph(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind a proxy
        },
    )
