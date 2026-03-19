import json
import logging
import os
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


# ── Request / response models ─────────────────────────────────────────────────

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

    try:
        async for chunk in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_updates in chunk.items():
                # node_updates is only the delta — merge it into the full state
                if isinstance(node_updates, dict):
                    current_state.update(node_updates)

                if node_name not in _PROGRESS_NODES:
                    continue

                # Convert 0-based index to 1-based for the frontend.
                # Note: after advance_chapter runs, the index already points to
                # the NEXT chapter — so treat `chapter` as supplementary context
                # only. The status_message (set by the graph) is the authoritative
                # human-readable description of what just happened.
                chapter_idx = current_state.get("current_chapter_index")
                chapter_num = chapter_idx + 1 if isinstance(chapter_idx, int) else None

                yield _sse({
                    "event": "node_done",
                    "node": node_name,
                    "chapter": chapter_num,          # 1-based, may lag by 1 after advance_chapter
                    "message": current_state.get("status_message", ""),   # primary field
                    "forced_chapters": current_state.get("forced_chapters", []),
                })

        # Final event — current_state now holds the fully accumulated graph output
        final_story = current_state.get("final_story")
        if final_story:
            yield _sse({
                "event": "done",
                "final_story": final_story,
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
