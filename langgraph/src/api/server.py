import asyncio
import hashlib
import json
import logging
import math
import os
import re
from io import BytesIO
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
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
app.mount("/sounds", StaticFiles(directory=_SOUNDS_DIR), name="sounds")


# ── TTS helpers ───────────────────────────────────────────────────────────────

def _chunk_text(text: str, max_chars: int = 4500) -> list[str]:
    """Split text on sentence boundaries so no chunk exceeds max_chars bytes."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # Hard-split a single sentence that is itself too long
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i : i + max_chars])
            continue
        if len(current) + len(sentence) + 1 > max_chars:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current += (" " if current else "") + sentence
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


def _pick_ambient_file(ambient: str) -> str | None:
    """Return the absolute path to the ambient file, or None if not found."""
    relative = _AMBIENT_FILES.get(ambient)
    if not relative:
        return None
    path = Path(_SOUNDS_DIR) / relative
    return str(path) if path.exists() else None


_TTS_PROMPT_PREFIX = (
    "# AUDIO PROFILE: Bedtime Science Narrator\n\n"
    "## DIRECTOR'S NOTES\n"
    "Style: Warm, calm, reassuring bedtime narrator — like David Attenborough reading a "
    "bedtime story. Full, clear voice with a relaxed and soothing tone. "
    "Do NOT whisper. Do NOT drop volume. Maintain a steady, full vocal presence throughout. "
    "The listener is lying in bed drifting off — the voice should feel like a gentle, "
    "trustworthy companion guiding them through the story.\n"
    "Pacing: Slow and unhurried. Natural pauses between sentences. Never rushed.\n"
    "Accent: Clear, neutral.\n\n"
    "## TRANSCRIPT\n"
)


def _synthesize_chunk(idx: int, chunk: str, voice_name: str, api_key: str) -> tuple[int, "AudioSegment"]:
    """Synthesize a single text chunk via Gemini TTS. Safe to call from threads."""
    import wave
    from google import genai
    from google.genai import types
    from pydub import AudioSegment

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=_TTS_PROMPT_PREFIX + chunk,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
        ),
    )
    pcm_data = response.candidates[0].content.parts[0].inline_data.data
    wav_buffer = BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm_data)
    wav_buffer.seek(0)
    from pydub import AudioSegment
    return idx, AudioSegment.from_wav(wav_buffer)


def _synthesize_blocking(
    story_text: str,
    voice_name: str,
    ambient: str,
    ambient_db: float,
    out_path: str,
) -> tuple[int, int]:
    """Synthesize story text via Gemini TTS, optionally mix ambient sound.

    Chunks are synthesized in parallel via ThreadPoolExecutor, then reassembled
    in order. Returns (duration_ms, chunks_synthesized).
    Runs synchronously — call via run_in_executor to avoid blocking the event loop.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pydub import AudioSegment

    api_key = os.environ.get("GOOGLE_API_KEY")
    chunks = _chunk_text(story_text, max_chars=4000)
    logger.info("TTS: synthesizing %d chunks in parallel", len(chunks))

    results: dict[int, AudioSegment] = {}
    with ThreadPoolExecutor(max_workers=min(len(chunks), 4)) as pool:
        futures = {
            pool.submit(_synthesize_chunk, i, chunk, voice_name, api_key): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx, seg = future.result()
            results[idx] = seg
            logger.info("TTS: chunk %d/%d done", idx + 1, len(chunks))

    # Reassemble in original order
    narration = sum((results[i] for i in range(len(chunks))), AudioSegment.empty())

    # Ambient mixing
    if ambient != "none":
        ambient_file = _pick_ambient_file(ambient)
        if ambient_file:
            try:
                amb_seg = AudioSegment.from_file(ambient_file)
                loops_needed = math.ceil(len(narration) / len(amb_seg))
                amb_looped = (amb_seg * loops_needed)[: len(narration)]
                amb_quiet = amb_looped + ambient_db
                narration = narration.overlay(amb_quiet)
            except Exception as exc:
                logger.warning("Ambient mixing failed (%s) — continuing narration-only: %s", ambient_file, exc)

    narration.export(out_path, format="mp3", bitrate="128k")
    return len(narration), len(chunks)


# ── Request / response models ─────────────────────────────────────────────────

class AudioRequest(BaseModel):
    story_text: str = Field(..., min_length=100, description="The final story text to convert to audio")
    voice: str = Field(
        default="Aoede",
        description='Gemini TTS voice name, e.g. "Aoede", "Sulafat", "Achernar", "Vindemiatrix"',
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
    voice: str = Field(default="Aoede", description="Gemini TTS voice name")
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
    "verify_facts",
    "reflect_chapter",
    "revise_chapter",
    "iterate_chapter",
    "advance_chapter",
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
                                request.ambient_db, audio_out,
                            )
                            logger.info("TTS synthesis started in background (parallel chunks).")
                        else:
                            logger.info("TTS cache hit — skipping synthesis.")

                if node_name not in _PROGRESS_NODES:
                    continue

                # Convert 0-based index to 1-based for the frontend.
                chapter_idx = current_state.get("current_chapter_index")
                chapter_num = chapter_idx + 1 if isinstance(chapter_idx, int) else None

                yield _sse({
                    "event": "node_done",
                    "node": node_name,
                    "chapter": chapter_num,
                    "message": current_state.get("status_message", ""),
                    "forced_chapters": current_state.get("forced_chapters", []),
                })

        # Graph complete — await TTS (may already be done by now)
        final_story = current_state.get("final_story")
        audio_url: str | None = None

        if synthesis_future is not None:
            try:
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
                "forced_chapters": current_state.get("forced_chapters", []),
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
        from pydub import AudioSegment
        duration_ms = len(AudioSegment.from_mp3(audio_path))
        return JSONResponse(content={
            "audio_url": f"/audio/{audio_filename}",
            "duration_seconds": duration_ms // 1000,
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
