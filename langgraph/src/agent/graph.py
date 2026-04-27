import json
import logging
import operator
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
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
    REVISION_PROMPT,
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

    # ── StoryGuard fields (set by storyguard / revision nodes) ──
    guard_result: dict           # full output of predict_suitable_4_6 (4-6 path)
    age_diagnosis: dict          # full output of predict_age_group
    predicted_age_group: str     # "4-6" | "7-12" | "13+"
    guard_passed: bool           # True if story matches target audience
    revision_instruction: str    # built by build_revision_instruction
    revision_count: int          # how many revision loops have run
    max_revisions: int           # max retry attempts before giving up (default 2)
    final_status: str            # "accepted" | "accepted_non_child" | "max_revisions_reached"


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


# ── SECTION 3: StoryGuard — Feature Extraction & Models ─────────────────────

# Audiences that require age-suitability checking after generation
_CHILD_AUDIENCES = {
    "children (ages 4–6)",
    "children (ages 7–12)",
    "children (ages 13+)",
}

# Model files are saved by the notebook into notebooks/ at the project root.
# Override via env var STORYGUARD_MODEL_DIR if you move them.
# graph.py is at: project/langgraph/src/agent/graph.py
# parents[3]    = project root (CountingStars/)
_MODEL_DIR = Path(
    os.getenv(
        "STORYGUARD_MODEL_DIR",
        str(Path(__file__).resolve().parents[3] / "notebooks"),
    )
)
logger.info("StoryGuard model dir: %s", _MODEL_DIR)

_TEXT_FEATURES = [
    "log_word_count", "sentence_count", "avg_sentence_length",
    "avg_word_length", "unique_word_ratio", "exclamation_ratio",
    "question_ratio", "flesch_score",
]


def _load_model(filename: str):
    path = _MODEL_DIR / filename
    if not path.exists():
        logger.warning("StoryGuard model not found: %s — will use heuristic fallback", path)
        return None
    try:
        model = joblib.load(path)
        logger.info("StoryGuard loaded: %s", filename)
        return model
    except Exception as exc:
        logger.warning(
            "StoryGuard model %s failed to load (sklearn version mismatch?): %s — "
            "falling back to heuristics. Re-save with the server's sklearn version to fix.",
            filename, exc,
        )
        return None


# Binary 4-6 suitability model (Gradient Boosting — no scaler needed)
_sg_suitable_4_6_model = _load_model("child_friendly_gb.joblib")

# Multiclass age group model (Gradient Boosting — no scaler needed)
_sg_multi_model = _load_model("age_group_gb.joblib")

_sg_id_to_age = {0: "4-6", 1: "7-12", 2: "13+"}


# ── Rule-based safety guard ───────────────────────────────────────────────────

_SCARY_WORDS = {
    "haunted", "ghost", "shadow", "midnight", "fear",
    "scary", "monster", "scream", "horror", "demon", "curse",
}
_VIOLENCE_WORDS = {
    "war", "soldier", "battlefield", "weapon", "gun", "fight",
    "ruin", "despair", "ash", "kill", "attack", "blood", "death",
    "murder", "corpse", "artillery", "casualties",
}


def rule_based_guard(text: str) -> tuple[bool, str]:
    """
    First-pass keyword safety filter for all child audiences.
    Returns (passed: bool, reason: str).
    """
    words         = set(re.findall(r"[a-zA-Z]+", text.lower()))
    violence_hits = words & _VIOLENCE_WORDS
    scary_hits    = words & _SCARY_WORDS
    if violence_hits:
        return False, f"Rejected by safety rule: violence-related words {violence_hits}"
    if len(scary_hits) >= 2:
        return False, f"Rejected by safety rule: scary content {scary_hits}"
    return True, "Passed rule-based safety check"


# ── Feature helpers (mirror of notebook Section 4) ───────────────────────────

def _sg_clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _sg_count_sentences(text: str) -> int:
    parts = re.split(r"[.!?]+", text)
    return max(len([p for p in parts if p.strip()]), 1)


def _sg_extract_words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _sg_approx_syllables(word: str) -> int:
    return max(len(re.findall(r"[aeiouy]+", word.lower())), 1)


def _sg_flesch(text: str) -> float:
    words = _sg_extract_words(text)
    n_w = max(len(words), 1)
    n_s = _sg_count_sentences(text)
    n_syl = sum(_sg_approx_syllables(w) for w in words)
    return round(206.835 - 1.015 * (n_w / n_s) - 84.6 * (n_syl / n_w), 2)


def _sg_extract_features(text: str) -> dict:
    words = _sg_extract_words(text)
    n_w = max(len(words), 1)
    n_s = _sg_count_sentences(text)
    lengths = [len(w) for w in words]
    return {
        "log_word_count":      round(np.log1p(n_w), 4),
        "sentence_count":      n_s,
        "avg_sentence_length": round(n_w / n_s, 2),
        "avg_word_length":     round(float(np.mean(lengths)), 2),
        "unique_word_ratio":   round(len(set(words)) / n_w, 2),
        "exclamation_ratio":   round(text.count("!") / n_w, 4),
        "question_ratio":      round(text.count("?") / n_w, 4),
        "flesch_score":        _sg_flesch(text),
        "raw_word_count":      n_w,
    }


def _sg_feature_matrix(features: dict) -> np.ndarray:
    """Convert feature dict → (1, 8) numpy array in correct column order."""
    return pd.DataFrame([features])[_TEXT_FEATURES].values


# ── Prediction helpers ────────────────────────────────────────────────────────

def predict_suitable_4_6(story_text: str) -> dict:
    """
    Binary check: is this story suitable for ages 4–6?
    Uses Gradient Boosting trained on age_group == '4-6' label.
    Falls back to readability heuristic if model unavailable.
    Returns suitable_4_6 (bool), confidence (float), and features.
    """
    text     = _sg_clean_text(story_text)
    features = _sg_extract_features(text)

    if _sg_suitable_4_6_model is None:
        suitable = features["flesch_score"] >= 70 and features["avg_word_length"] <= 4.5
        return {
            "suitable_4_6":               suitable,
            "confidence":                 0.6,
            "ml_probability_suitable_4_6": None,
            "features":                   features,
            "fallback":                   True,
        }

    X    = _sg_feature_matrix(features)
    label = int(_sg_suitable_4_6_model.predict(X)[0])
    prob  = float(_sg_suitable_4_6_model.predict_proba(X)[0][1])

    predicted_suitable = label == 1
    confidence         = prob if predicted_suitable else (1 - prob)

    # Readability override: very easy text → suitable
    if features["flesch_score"] >= 80 and features["avg_word_length"] <= 4.5:
        return {
            "suitable_4_6":               True,
            "confidence":                 round(max(confidence, 0.75), 3),
            "ml_probability_suitable_4_6": round(prob, 3),
            "features":                   features,
            "readability_override":       True,
        }

    return {
        "suitable_4_6":               predicted_suitable,
        "confidence":                 round(confidence, 3),
        "ml_probability_suitable_4_6": round(prob, 3),
        "features":                   features,
        "readability_override":       False,
    }


def predict_age_group(story_text: str) -> dict:
    """
    Multiclass age group prediction: '4-6' | '7-12' | '13+'.
    Uses Gradient Boosting multiclass model.
    Falls back to Flesch score heuristic if model unavailable.
    """
    text     = _sg_clean_text(story_text)
    features = _sg_extract_features(text)

    if _sg_multi_model is None:
        flesch = features["flesch_score"]
        predicted = "4-6" if flesch >= 70 else ("7-12" if flesch >= 50 else "13+")
        return {
            "predicted_age": predicted,
            "probabilities": {"4-6": 0.0, "7-12": 0.0, "13+": 0.0},
            "features":      features,
            "fallback":      True,
        }

    X        = _sg_feature_matrix(features)
    pred_idx = int(_sg_multi_model.predict(X)[0])
    probs    = _sg_multi_model.predict_proba(X)[0]
    return {
        "predicted_age": _sg_id_to_age[pred_idx],
        "probabilities": {_sg_id_to_age[i]: round(float(p), 3) for i, p in enumerate(probs)},
        "features":      features,
        "fallback":      False,
    }


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


# ── StoryGuard Nodes ─────────────────────────────────────────────────────────

def _failed_status(state: StoryState) -> str:
    """Return 'max_revisions_reached' if retries are exhausted, else 'needs_revision'."""
    return (
        "max_revisions_reached"
        if state.get("revision_count", 0) >= state.get("max_revisions", 2)
        else "needs_revision"
    )


def storyguard_check(state: StoryState) -> dict:
    """
    Check whether the polished story matches the target audience.

    - ages 4–6  → binary suitable_4_6 model (GB), then multiclass if needed
    - ages 7–12 → multiclass: predicted_age == "7-12"?
    - ages 13+  → multiclass: predicted_age == "13+"?
    - non-child → skip, pass immediately
    """
    audience = state["audience"]
    story    = state["final_story"]

    if audience not in _CHILD_AUDIENCES:
        logger.info("[storyguard_check] non-child audience — skipping guard")
        return {
            "guard_passed": True,
            "final_status": "accepted_non_child",
            "status_message": "StoryGuard skipped for non-child audience.",
        }

    # Layer 1: rule-based safety check for all child audiences
    safety_passed, safety_reason = rule_based_guard(story)
    if not safety_passed:
        logger.info("[storyguard_check] safety rule failed: %s", safety_reason)
        return {
            "guard_passed":  False,
            "final_status":  _failed_status(state),
            "guard_result":  {"safety_passed": False, "reason": safety_reason},
            "status_message": safety_reason,
        }

    if audience == "children (ages 4–6)":
        result = predict_suitable_4_6(story)
        passed = result["suitable_4_6"]
        logger.info("[storyguard_check] 4-6 binary: passed=%s conf=%.2f",
                    passed, result["confidence"])
        return {
            "guard_result":  result,
            "guard_passed":  passed,
            "final_status":  "accepted" if passed else _failed_status(state),
            "status_message": (
                f"StoryGuard 4–6 binary: {'PASS' if passed else 'FAIL'} "
                f"(conf={result['confidence']:.2f})"
            ),
        }

    # 7-12 or 13+: use multiclass
    target     = "7-12" if audience == "children (ages 7–12)" else "13+"
    age_result = predict_age_group(story)
    predicted  = age_result["predicted_age"]
    passed     = predicted == target
    logger.info("[storyguard_check] multiclass: predicted=%s target=%s passed=%s",
                predicted, target, passed)
    return {
        "age_diagnosis":       age_result,
        "predicted_age_group": predicted,
        "guard_passed":        passed,
        "final_status":        "accepted" if passed else _failed_status(state),
        "status_message": (
            f"StoryGuard multiclass: predicted={predicted} target={target} "
            f"{'PASS' if passed else 'FAIL'}"
        ),
    }


def diagnose_age(state: StoryState) -> dict:
    """
    Run the multiclass age model to find out which age group the story looks like.
    Only needed for the 4–6 path (7-12/13+ already have age_diagnosis from storyguard_check).
    """
    if state.get("age_diagnosis"):
        return {}  # already diagnosed in storyguard_check

    result   = predict_age_group(state["final_story"])
    predicted = result["predicted_age"]
    logger.info("[diagnose_age] story looks like age group: %s", predicted)
    return {
        "age_diagnosis":      result,
        "predicted_age_group": predicted,
        "status_message": f"Age diagnosis: story reads like ages {predicted}.",
    }


def build_revision_instruction(state: StoryState) -> dict:
    """Build a targeted LLM revision instruction based on target vs. predicted age group."""
    audience  = state["audience"]
    predicted = state.get("predicted_age_group") or (
        state.get("age_diagnosis", {}).get("predicted_age")
    )

    if audience == "children (ages 4–6)":
        if predicted == "7-12":
            instruction = (
                "Revise the story for ages 4–6. "
                "The current version reads like a 7–12 story — simplify it:\n"
                "- Use shorter sentences.\n"
                "- Replace difficult words with everyday ones.\n"
                "- Reduce explanation density; show through actions and images instead.\n"
                "- Add gentle repetition and a calm, warm rhythm.\n"
                "- Keep the same topic and main story arc."
            )
        elif predicted == "13+":
            instruction = (
                "Rewrite the story for ages 4–6. "
                "The current version reads like a 13+ story — make a major simplification:\n"
                "- Use very short sentences (5–8 words each).\n"
                "- Use only common, concrete words.\n"
                "- Remove all abstract explanations.\n"
                "- Keep only 1–2 simple science ideas.\n"
                "- Explain through actions, colors, sounds, and concrete images.\n"
                "- Make the story slow, calm, and soothing."
            )
        else:
            instruction = (
                "Revise the story to better fit ages 4–6:\n"
                "- Use simpler words and shorter sentences.\n"
                "- Make it gentle, concrete, and easy to follow."
            )

    elif audience == "children (ages 7–12)":
        if predicted == "4-6":
            instruction = (
                "Revise the story for ages 7–12. "
                "The current version is too simple — enrich it slightly:\n"
                "- Add more scientific detail and cause-and-effect reasoning.\n"
                "- Use slightly richer vocabulary.\n"
                "- Reduce overly childish repetition.\n"
                "- Keep the story clear, friendly, and imaginative."
            )
        elif predicted == "13+":
            instruction = (
                "Revise the story for ages 7–12. "
                "The current version is too advanced — simplify it:\n"
                "- Shorten long sentences.\n"
                "- Explain or replace advanced terms.\n"
                "- Reduce abstract language; use concrete examples and simple analogies.\n"
                "- Keep the science accurate but accessible."
            )
        else:
            instruction = "Revise the story to better fit ages 7–12."

    elif audience == "children (ages 13+)":
        if predicted == "4-6":
            instruction = (
                "Revise the story for ages 13+. "
                "The current version is too simple — make it more mature:\n"
                "- Add deeper scientific explanation and precise vocabulary.\n"
                "- Add richer context, reasoning, and real-world connections.\n"
                "- Reduce childish repetition.\n"
                "- Keep the story engaging and clear."
            )
        elif predicted == "7-12":
            instruction = (
                "Revise the story for ages 13+. "
                "The current version is slightly too simple — increase depth:\n"
                "- Add more complex reasoning and precise scientific terms.\n"
                "- Expand explanations with nuance and real-world connections.\n"
                "- Maintain the story structure; just raise the intellectual level."
            )
        else:
            instruction = "Revise the story to better fit ages 13+."

    else:
        instruction = "Improve the story to better match the selected audience."

    logger.info("[build_revision_instruction] target=%s predicted=%s", audience, predicted)
    return {
        "revision_instruction": instruction,
        "status_message": (
            f"Revision instruction built: target={audience}, predicted={predicted}."
        ),
    }


def revise_story(state: StoryState) -> dict:
    """Send the story back to the LLM with a targeted revision instruction."""
    chain = PromptTemplate.from_template(REVISION_PROMPT) | generation_llm | parser
    revised = chain.invoke({
        "audience":             state["audience"],
        "revision_instruction": state["revision_instruction"],
        "story":                state["final_story"],
    }).strip()

    count = state.get("revision_count", 0) + 1
    logger.info("[revise_story] revision #%d done — %d words", count, len(revised.split()))
    return {
        "final_story":    revised,
        "revision_count": count,
        "status_message": f"Story revised (attempt {count}).",
    }


def route_after_guard(state: StoryState) -> str:
    """Route after storyguard_check: accept, retry, or give up."""
    if state.get("guard_passed"):
        return "accept"
    if state.get("revision_count", 0) >= state.get("max_revisions", 2):
        return "max_revisions_reached"
    return "diagnose_age"


# ── SECTION 6: Dispatch ──────────────────────────────────────────────────────


def dispatch_chapters(state: StoryState) -> list[Send]:
    """Fan out: send one write_chapter task per chapter, all run in parallel."""
    return [
        Send("write_chapter", {**state, "chapter_index": i})
        for i in range(state["num_chapters"])
    ]


# ── SECTION 7: Graph Assembly ────────────────────────────────────────────────

builder = StateGraph(StoryState)

# Generation nodes
builder.add_node("plan_story",         plan_story)
builder.add_node("write_chapter",      write_chapter)
builder.add_node("assemble_chapters",  assemble_chapters)
builder.add_node("polish_story",       polish_story)

# StoryGuard nodes
builder.add_node("storyguard_check",           storyguard_check)
builder.add_node("diagnose_age",               diagnose_age)
builder.add_node("build_revision_instruction", build_revision_instruction)
builder.add_node("revise_story",               revise_story)

builder.set_entry_point("plan_story")

# plan_story → dispatch_chapters fans out to N parallel write_chapter nodes
builder.add_conditional_edges("plan_story", dispatch_chapters, ["write_chapter"])

# All write_chapter branches converge at assemble_chapters
builder.add_edge("write_chapter",     "assemble_chapters")
builder.add_edge("assemble_chapters", "polish_story")

# polish_story → StoryGuard (instead of END)
builder.add_edge("polish_story", "storyguard_check")

# storyguard_check → END (pass) | mark_max_revisions | diagnose_age
builder.add_conditional_edges(
    "storyguard_check",
    route_after_guard,
    {
        "accept":                END,
        "max_revisions_reached": END,
        "diagnose_age":          "diagnose_age",
    },
)

# Revision loop: diagnose → build instruction → revise → check again
builder.add_edge("diagnose_age",               "build_revision_instruction")
builder.add_edge("build_revision_instruction", "revise_story")
builder.add_edge("revise_story",               "storyguard_check")

graph = builder.compile()
