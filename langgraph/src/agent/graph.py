import json
import logging
import operator
import os
import re
from typing import Annotated, Optional

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from agent.config import get_audience
from agent.prompts import (
    select_chapter_prompt,
    select_plan_prompt,
    select_polish_prompt,
)

load_dotenv()

logger = logging.getLogger(__name__)

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

    tts_speed: float                    # set by caller; used by plan_story to calibrate word count

    final_story: Optional[str]         # set by polish_story
    # Annotated with last-wins reducer — parallel write_chapter nodes all emit this
    status_message: Annotated[Optional[str], lambda _, b: b]


# ── SECTION 2: Duration → Story Parameter Helper ─────────────────────────────

# Maps duration_min to a sensible chapter count so pacing stays natural.
_DURATION_TO_CHAPTERS = [
    (10,  3),
    (15,  4),
    (20,  5),
    (25,  6),
]

_DEFAULT_SPEED: float = 0.80  # fallback when tts_speed not in state
_TTS_HEADROOM:  float = 0.95  # reserve ~5% for chapter pauses and natural breathing


def derive_story_params(
    duration_min: int,
    audience: str = "",
    tts_speed: float | None = None,
) -> tuple[int, int, int]:
    """Return (num_chapters, target_total_words, words_per_chapter) for a given duration."""
    spec  = get_audience(audience)
    speed = tts_speed if tts_speed is not None else _DEFAULT_SPEED
    effective_wpm = spec.wpm * speed  # keep float; int() only at final product

    num_chapters = spec.max_chapters
    for threshold, chapters in _DURATION_TO_CHAPTERS:
        if duration_min <= threshold:
            num_chapters = min(spec.max_chapters, chapters)
            break

    target_total_words = int(duration_min * effective_wpm * _TTS_HEADROOM)
    words_per_chapter  = target_total_words // num_chapters
    if spec.max_words_per_chapter is not None:
        words_per_chapter = min(words_per_chapter, spec.max_words_per_chapter)
    target_total_words = words_per_chapter * num_chapters  # re-sync after cap
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


# ── SECTION 3: LLM & Parser ───────────────────────────────────────────────────

# Generation: most capable model for rich, creative story writing and polishing
generation_llm = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview", temperature=0.75
)

parser = StrOutputParser()


# ── SECTION 4: Node Functions ────────────────────────────────────────────────


def plan_story(state: StoryState) -> dict:
    """Derive story parameters from duration, then generate the chapter outline."""
    logger.info("=" * 60)
    logger.info("[plan_story] topic='%s' domain='%s' duration=%dmin",
                state["topic"], state["domain"], state["duration_min"])

    audience = state["audience"]
    num_chapters, target_total_words, words_per_chapter = derive_story_params(
        state["duration_min"], audience, tts_speed=state.get("tts_speed")
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

    spec   = get_audience(state["audience"])
    cap    = spec.max_words_per_chapter
    target = min(state["words_per_chapter"], cap) if cap is not None else state["words_per_chapter"]
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


# ── SECTION 5: Dispatch ──────────────────────────────────────────────────────


def dispatch_chapters(state: StoryState) -> list[Send]:
    """Fan out: send one write_chapter task per chapter, all run in parallel."""
    return [
        Send("write_chapter", {**state, "chapter_index": i})
        for i in range(state["num_chapters"])
    ]


# ── SECTION 6: Graph Assembly ────────────────────────────────────────────────

builder = StateGraph(StoryState)

builder.add_node("plan_story",         plan_story)
builder.add_node("write_chapter",      write_chapter)
builder.add_node("assemble_chapters",  assemble_chapters)
builder.add_node("polish_story",       polish_story)

builder.set_entry_point("plan_story")

# plan_story → dispatch_chapters fans out to N parallel write_chapter nodes
builder.add_conditional_edges("plan_story", dispatch_chapters, ["write_chapter"])

# All write_chapter branches converge at assemble_chapters
builder.add_edge("write_chapter",     "assemble_chapters")
builder.add_edge("assemble_chapters", "polish_story")
builder.add_edge("polish_story",      END)

graph = builder.compile()
