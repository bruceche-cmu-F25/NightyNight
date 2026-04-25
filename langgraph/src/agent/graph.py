import json
import logging
import operator
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_milvus import Milvus
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from pymilvus import connections, utility
from typing_extensions import TypedDict

from agent.prompts import (
    select_chapter_prompt,
    select_plan_prompt,
    select_polish_prompt,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ── RAG / Milvus Config ───────────────────────────────────────────────────────

_MILVUS_URI = os.getenv("MILVUS_URI", "http://34.67.37.109:19530")
# _MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
_MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
_MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "science_knowledge")
_MILVUS_INDEX = os.getenv("INDEX_TYPE", "HNSW").upper()
_RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
_EMB_MODEL = os.getenv("GEMINI_EMB_MODEL", "gemini-embedding-001")

# ── SECTION 1: State ─────────────────────────────────────────────────────────


class ChapterPlan(TypedDict):
    title: str    # e.g. "The Night Everything Began"
    summary: str  # 1-2 sentence description of what this chapter covers


class _StoryStateRequired(TypedDict, total=True):
    """Fields that MUST be supplied by the caller before the graph runs."""
    topic: str
    duration_min: int   # target listening duration, e.g. 10 / 15 / 20 / 25
    style: str          # narration style, e.g. "calm documentary", "gentle bedtime"
    audience: str       # target audience, e.g. "curious adults", "science enthusiasts"
    domain: str         # science domain, e.g. "astronomy", "biology", "history of science"


class StoryState(_StoryStateRequired, total=False):
    """Full graph state.  Required fields inherited from _StoryStateRequired (total=True).
    Everything below is optional — nodes populate these fields incrementally.
    """

    # ── Derived from duration_min by plan_story ──
    num_chapters: int
    target_total_words: int
    words_per_chapter: int

    # ── Pipeline state ──
    chapter_plans: list[ChapterPlan]   # set by plan_story

    # Per-Send field: which chapter this write_chapter invocation is writing
    chapter_index: int

    # Parallel collection — reducer appends each (index, text) tuple from parallel writes
    chapter_drafts: Annotated[list[tuple[int, str]], operator.add]

    # Assembled in order by assemble_chapters
    completed_chapters: list[str]

    final_story: Optional[str]         # set by polish_story
    # Annotated with last-wins reducer — parallel write_chapter nodes all emit this
    status_message: Annotated[Optional[str], lambda _, b: b]


# ── SECTION 2: Duration → Story Parameter Helper ─────────────────────────────

# Calm narration pace: ~135 words per minute
_WORDS_PER_MIN = 135

# Maps duration_min to a sensible chapter count so pacing stays natural.
_DURATION_TO_CHAPTERS = [
    (10,  3),
    (15,  4),
    (20,  5),
    (25,  6),
]

# Per-audience words-per-minute cap.
# Young children need shorter chapters regardless of duration setting.
_AUDIENCE_WPM: dict[str, int] = {
    "children (ages 4–6)":  65,   # ~500 words / chapter max
    "children (ages 7–12)": 95,
    "children (ages 13+)":  115,
}
_DEFAULT_WPM = 135

_AUDIENCE_MAX_WORDS_PER_CHAPTER: dict[str, int] = {
    "children (ages 4–6)":  650,
    "children (ages 7–12)": 1000,
}


def _cap_words_per_chapter(audience: str, words: int) -> int:
    cap = _AUDIENCE_MAX_WORDS_PER_CHAPTER.get(audience)
    return min(words, cap) if cap else words

# Young children also get fewer chapters so each stays simple.
_AUDIENCE_MAX_CHAPTERS: dict[str, int] = {
    "children (ages 4–6)":  4,
    "children (ages 7–12)": 5,
}


def derive_story_params(duration_min: int, audience: str = "") -> tuple[int, int, int]:
    """Return (num_chapters, target_total_words, words_per_chapter) for a given duration."""
    wpm = _AUDIENCE_WPM.get(audience, _DEFAULT_WPM)
    max_ch = _AUDIENCE_MAX_CHAPTERS.get(audience, _DURATION_TO_CHAPTERS[-1][1])

    num_chapters = min(max_ch, _DURATION_TO_CHAPTERS[-1][1])
    for threshold, chapters in _DURATION_TO_CHAPTERS:
        if duration_min <= threshold:
            num_chapters = min(max_ch, chapters)
            break

    target_total_words = duration_min * wpm
    words_per_chapter = target_total_words // num_chapters
    return num_chapters, target_total_words, words_per_chapter


def _parse_chapter_plans(raw: str, expected_count: int) -> list[ChapterPlan]:
    """Parse and validate the JSON chapter outline returned by the LLM."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Chapter outline is not valid JSON.\n"
            f"Parser error: {exc}\n"
            f"Raw output:\n{raw}"
        ) from exc

    if not isinstance(data, list):
        raise ValueError(
            f"Expected a JSON array of chapter plans, got {type(data).__name__}.\n"
            f"Raw output:\n{raw}"
        )

    if len(data) != expected_count:
        raise ValueError(
            f"Expected {expected_count} chapters, but model returned {len(data)}.\n"
            f"Raw output:\n{raw}"
        )

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Chapter {i + 1} is not a JSON object: {item!r}")
        missing = [k for k in ("title", "summary") if k not in item]
        if missing:
            raise ValueError(
                f"Chapter {i + 1} is missing required key(s): {missing}. Got: {item!r}"
            )
        if not isinstance(item["title"], str) or not item["title"].strip():
            raise ValueError(f"Chapter {i + 1} has an empty or non-string 'title': {item!r}")
        if not isinstance(item["summary"], str) or not item["summary"].strip():
            raise ValueError(f"Chapter {i + 1} has an empty or non-string 'summary': {item!r}")

    return [ChapterPlan(title=c["title"], summary=c["summary"]) for c in data]


# ── SECTION 4: LLM & Parser ───────────────────────────────────────────────────

# Generation: most capable model for rich, creative story writing and polishing
generation_llm = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview", temperature=0.75
)

parser = StrOutputParser()


# ── SECTION 4b: RAG Helpers (used by ingest_sources utility) ─────────────────

_embeddings: Optional[GoogleGenerativeAIEmbeddings] = None
_vector_store: Optional[Milvus] = None


def _get_vector_store() -> Optional[Milvus]:
    """Return a cached Milvus connection, or None if Milvus is unavailable."""
    global _embeddings, _vector_store
    if _vector_store is not None:
        return _vector_store
    try:
        if _embeddings is None:
            _embeddings = GoogleGenerativeAIEmbeddings(model=_EMB_MODEL)
        conn_args: Dict[str, Any] = {"uri": _MILVUS_URI}
        if _MILVUS_TOKEN:
            conn_args["token"] = _MILVUS_TOKEN
        _vector_store = Milvus(
            embedding_function=_embeddings,
            collection_name=_MILVUS_COLLECTION,
            connection_args=conn_args,
            index_params={"index_type": _MILVUS_INDEX, "metric_type": "COSINE",
                          "params": {"M": 16, "efConstruction": 200}},
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            auto_id=True,
            drop_old=False,
        )
        return _vector_store
    except Exception as exc:
        logger.warning("Milvus unavailable: %s", exc)
        return None


# Chunking params (override via env)
_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))


def ingest_sources(sources_dir: str, drop_old: bool = False) -> Dict[str, Any]:
    """Chunk and index all PDFs under sources_dir/{domain}/ into Milvus.

    Expected layout:
        sources_dir/
            cosmos/         ← folder name becomes the domain tag
                book.pdf
            life/
                bio.pdf
            civilization/
                history.pdf

    Each chunk is stored with metadata: {domain, source, chunk_id}.
    Call with drop_old=True to wipe and rebuild the collection from scratch.
    """
    from io import BytesIO

    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from pypdf import PdfReader

    global _embeddings  # noqa: PLW0603
    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(model=_EMB_MODEL)

    conn_args: Dict[str, Any] = {"uri": _MILVUS_URI}
    if _MILVUS_TOKEN:
        conn_args["token"] = _MILVUS_TOKEN

    vs = Milvus(
        embedding_function=_embeddings,
        collection_name=_MILVUS_COLLECTION,
        connection_args=conn_args,
        index_params={"index_type": _MILVUS_INDEX, "metric_type": "COSINE",
                      "params": {"M": 16, "efConstruction": 200}},
        search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        auto_id=True,
        drop_old=drop_old,
    )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )

    all_docs: List[Document] = []
    domain_stats: Dict[str, int] = {}
    skipped: List[str] = []

    for domain_entry in sorted(os.scandir(sources_dir), key=lambda e: e.name):
        if not domain_entry.is_dir():
            continue
        domain = domain_entry.name
        pdf_count = 0

        for file_entry in sorted(os.scandir(domain_entry.path), key=lambda e: e.name):
            if not file_entry.is_file() or not file_entry.name.lower().endswith(".pdf"):
                continue
            try:
                raw_bytes = Path(file_entry.path).read_bytes()
                reader = PdfReader(BytesIO(raw_bytes))
                full_text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
                if not full_text:
                    raise ValueError("no extractable text")
            except Exception as exc:
                logger.warning("Skipping %s: %s", file_entry.path, exc)
                skipped.append(file_entry.name)
                continue

            for i, chunk in enumerate(splitter.split_text(full_text)):
                all_docs.append(Document(
                    page_content=chunk,
                    metadata={"domain": domain, "source": file_entry.name, "chunk_id": i},
                ))
            pdf_count += 1

        domain_stats[domain] = pdf_count

    _INGEST_BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "200"))
    _INGEST_BATCH_PAUSE = float(os.getenv("INGEST_BATCH_PAUSE_SEC", "5"))

    for batch_start in range(0, len(all_docs), _INGEST_BATCH_SIZE):
        batch = all_docs[batch_start: batch_start + _INGEST_BATCH_SIZE]
        vs.add_documents(batch)
        logger.info(
            "Ingested chunks %d–%d / %d",
            batch_start + 1, batch_start + len(batch), len(all_docs),
        )
        if batch_start + _INGEST_BATCH_SIZE < len(all_docs):
            time.sleep(_INGEST_BATCH_PAUSE)

    logger.info("Ingested %d chunks across domains: %s", len(all_docs), domain_stats)

    return {
        "total_chunks": len(all_docs),
        "chunk_size": _CHUNK_SIZE,
        "chunk_overlap": _CHUNK_OVERLAP,
        "domains": domain_stats,
        "skipped": skipped,
    }


# ── SECTION 5: Node Functions ────────────────────────────────────────────────


def plan_story(state: StoryState) -> dict:
    """Derive story parameters from duration, then generate the chapter outline."""
    logger.info("=" * 60)
    logger.info("[plan_story] topic='%s' domain='%s' duration=%dmin",
                state["topic"], state["domain"], state["duration_min"])

    audience = state["audience"]
    num_chapters, target_total_words, words_per_chapter = derive_story_params(
        state["duration_min"], audience
    )

    plan_prompt = select_plan_prompt(audience)
    chain = PromptTemplate.from_template(plan_prompt) | generation_llm | parser
    raw = chain.invoke({
        "topic": state["topic"],
        "domain": state["domain"],
        "audience": audience,
        "style": state["style"],
        "duration_min": state["duration_min"],
        "num_chapters": num_chapters,
        "target_total_words": target_total_words,
        "words_per_chapter": words_per_chapter,
    }).strip()

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    chapter_plans = _parse_chapter_plans(raw, num_chapters)
    for i, p in enumerate(chapter_plans):
        logger.info("  ch%d: %s — %s", i + 1, p["title"], p["summary"])

    return {
        "num_chapters": num_chapters,
        "target_total_words": target_total_words,
        "words_per_chapter": words_per_chapter,
        "chapter_plans": chapter_plans,
        "chapter_drafts": [],
        "status_message": (
            f"Outline ready: {num_chapters} chapters, "
            f"~{words_per_chapter} words each, "
            f"target {state['duration_min']} min."
        ),
    }


def write_chapter(state: dict) -> dict:
    """Write one chapter. Invoked in parallel for all chapters via Send."""
    idx = state["chapter_index"]
    plans: list[ChapterPlan] = state["chapter_plans"]
    plan = plans[idx]
    num = state["num_chapters"]

    # Build a readable outline of all chapters so each writer knows the full arc
    full_outline = "\n".join(
        f"  Ch{i + 1}: {p['title']} — {p['summary']}"
        for i, p in enumerate(plans)
    )

    target = _cap_words_per_chapter(state["audience"], state["words_per_chapter"])
    chapter_prompt = select_chapter_prompt(state["audience"])
    chain = PromptTemplate.from_template(chapter_prompt) | generation_llm | parser
    draft = chain.invoke({
        "chapter_num": idx + 1,
        "num_chapters": num,
        "topic": state["topic"],
        "domain": state["domain"],
        "title": plan["title"],
        "summary": plan["summary"],
        "audience": state["audience"],
        "style": state["style"],
        "words_per_chapter": target,
        "words_min": int(target * 0.75),
        "words_max": int(target * 1.25),
        "full_outline": full_outline,
    }).strip()

    word_count = len(draft.split())
    logger.info("[write_chapter] ch%d/%d done — %d words: '%s'",
                idx + 1, num, word_count, plan["title"])

    return {
        "chapter_drafts": [(idx, draft)],
        "status_message": f"Chapter {idx + 1}/{num} written: \"{plan['title']}\"",
    }


def assemble_chapters(state: StoryState) -> dict:
    """Sort parallel chapter drafts by index and assemble into completed_chapters."""
    sorted_drafts = sorted(state.get("chapter_drafts", []), key=lambda x: x[0])
    completed = [text for _, text in sorted_drafts]
    logger.info("[assemble_chapters] assembled %d chapters in order", len(completed))
    return {
        "completed_chapters": completed,
        "status_message": f"All {len(completed)} chapters assembled.",
    }


def polish_story(state: StoryState) -> dict:
    """Final editing pass over the assembled story for consistent tone and flow."""
    logger.info("=" * 60)
    logger.info("[polish_story] %d chapters, running final polish...",
                len(state["completed_chapters"]))
    joined = "\n\n".join(state["completed_chapters"])

    chain = PromptTemplate.from_template(select_polish_prompt(state["audience"])) | generation_llm | parser
    polished = chain.invoke({
        "joined_chapters": joined,
        "target_total_words": state["target_total_words"],
    }).strip()

    logger.info("[polish_story] done — final story %d words", len(polished.split()))
    return {
        "final_story": polished,
        "status_message": "Story complete and polished.",
    }


# ── SECTION 6: Dispatch ──────────────────────────────────────────────────────


def dispatch_chapters(state: StoryState) -> list[Send]:
    """Fan out: send one write_chapter task per chapter, all run in parallel."""
    return [
        Send("write_chapter", {**state, "chapter_index": i})
        for i in range(state["num_chapters"])
    ]


# ── SECTION 7: Graph Assembly ────────────────────────────────────────────────

builder = StateGraph(StoryState)

builder.add_node("plan_story", plan_story)
builder.add_node("write_chapter", write_chapter)
builder.add_node("assemble_chapters", assemble_chapters)
builder.add_node("polish_story", polish_story)

builder.set_entry_point("plan_story")

# plan_story → dispatch_chapters fans out to N parallel write_chapter nodes
builder.add_conditional_edges("plan_story", dispatch_chapters, ["write_chapter"])

# All write_chapter branches converge at assemble_chapters
builder.add_edge("write_chapter", "assemble_chapters")
builder.add_edge("assemble_chapters", "polish_story")
builder.add_edge("polish_story", END)

graph = builder.compile()
