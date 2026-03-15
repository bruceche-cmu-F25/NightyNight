import json
import re
from typing import Optional

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

load_dotenv()

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
                        # used in prompts, RAG queries, and future TTS voice selection


class StoryState(_StoryStateRequired, total=False):
    """Full graph state.  Required fields are inherited from _StoryStateRequired (total=True).
    Everything below is optional — nodes populate these fields incrementally.
    """

    # ── Derived from duration_min by plan_story ──
    num_chapters: int           # how many chapters to generate
    target_total_words: int     # total word count goal for the finished story
    words_per_chapter: int      # target per chapter = target_total_words // num_chapters

    # ── Pipeline state ──
    chapter_plans: list[ChapterPlan]  # set by plan_story
    current_chapter_index: int         # which chapter we're currently writing
    current_chapter_draft: Optional[str]
    reflect_feedback: Optional[str]
    reflect_passed: Optional[bool]
    chapter_rewrite_count: int         # resets to 0 for each new chapter
    completed_chapters: list[str]      # approved chapter texts in order
    forced_chapters: list[int]         # indices of chapters force-advanced after max retries
    final_story: Optional[str]         # set by polish_story
    status_message: Optional[str]


# ── SECTION 2: Duration → Story Parameter Helper ─────────────────────────────

# Calm narration pace: ~135 words per minute
_WORDS_PER_MIN = 135

# Maps duration_min to a sensible chapter count so pacing stays natural.
# Shorter episodes → fewer, fuller chapters; longer → more chapters, similar length each.
_DURATION_TO_CHAPTERS = [
    (10,  3),
    (15,  4),
    (20,  5),
    (25,  6),
]


def derive_story_params(duration_min: int) -> tuple[int, int, int]:
    """Return (num_chapters, target_total_words, words_per_chapter) for a given duration."""
    # Pick the closest chapter count from the table (clamp to boundaries)
    num_chapters = _DURATION_TO_CHAPTERS[-1][1]
    for threshold, chapters in _DURATION_TO_CHAPTERS:
        if duration_min <= threshold:
            num_chapters = chapters
            break

    target_total_words = duration_min * _WORDS_PER_MIN
    words_per_chapter = target_total_words // num_chapters
    return num_chapters, target_total_words, words_per_chapter


def _parse_chapter_plans(raw: str, expected_count: int) -> list[ChapterPlan]:
    """Parse and validate the JSON chapter outline returned by the LLM.

    Raises ValueError with a descriptive message on any structural problem
    so the failure is obvious during debugging rather than a cryptic KeyError
    or AttributeError later in the pipeline.
    """
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


# ── SECTION 3: Prompts (Structured Prompt Format) ────────────────────────────

PLAN_PROMPT = """\
#Role: You are a science educator and narrative producer creating structured \
outlines for an evening science podcast. Your content is calm and accessible, \
but always grounded in real science — not just atmosphere.

#Task: Create a {num_chapters}-chapter story outline for a bedtime science story.

#Topic: {topic}

#Context:
  Domain: {domain}
  Target audience: {audience}
  Narration style: {style}
  Target duration: {duration_min} minutes (~{target_total_words} words total)
  Words per chapter: ~{words_per_chapter}

#Format: Return ONLY a valid JSON array with exactly {num_chapters} objects. \
No markdown fences, no extra text, no commentary.
[
  {{"title": "...", "summary": "..."}},
  ...
]
Each "summary" must name the specific scientific concept or fact that chapter covers — \
not just a mood or atmosphere.

#Tone / Style: {style} — calm and accessible, but substantive. \
The listener should feel at ease AND come away having genuinely learned something.

#Goal: An outline where each chapter has a clear educational payload \
delivered at a pace that does not disrupt sleep — paced for {duration_min} minutes.

#Requirements / Constraints:
- Distribute the narrative arc evenly across exactly {num_chapters} chapters:
  * First chapter: a grounded, relatable entry point that names the topic concretely
  * Middle chapters: each must cover a distinct, named scientific concept or mechanism
  * Second-to-last chapter: the most significant fact or discovery — stated precisely
  * Final chapter: a reflective close that links the science back to everyday human experience
- Each chapter summary must specify what the listener will learn, not just how it will feel
- Do not use "Chapter 1", "Chapter 2" etc. as titles — use clear, descriptive prose titles
- Each chapter summary should be distinct and non-overlapping in scientific content
- Each chapter should sustain approximately {words_per_chapter} words of narration
"""

WRITE_CHAPTER_PROMPT = """\
#Role: You are a science narrator with dual expertise: you understand the \
science deeply, and you know how to explain it in a calm, unhurried way \
that is pleasant to listen to while drifting toward sleep.

#Task: Write chapter {chapter_num} of {num_chapters} of the story.

#Topic: The story is about "{topic}" (domain: {domain}).

#Context:
  Chapter title: {title}
  Chapter focus: {summary}
  Target audience: {audience}
  Story so far (for narrative continuity):
  ---
  {story_so_far}
  ---

#Format: Plain prose only. No title, no headers, no bullet points. \
Target approximately {words_per_chapter} words.

#Tone / Style: {style} — warm and unhurried. Short sentences. Natural pauses. \
Analogies drawn from everyday life to make abstract concepts land clearly.

#Goal: Deliver the scientific content in this chapter's focus area in a way \
that is genuinely informative AND easy to absorb while relaxed. \
The listener should remember at least one concrete fact from this chapter.

#Requirements / Constraints:
- Each chapter must contain at least 2–3 concrete, accurate scientific facts \
  or mechanisms — not just mood or imagery
- Analogies and atmosphere should serve the science, not replace it
- Do not let more than 3 consecutive sentences pass without grounding the \
  reader in a specific fact, measurement, name, or mechanism
- Do not use "firstly", "secondly", "finally", or any list-like transitions
- Do not include the chapter title in your output
- Sentences should vary in length but favor short ones for a slow, breathing rhythm
- Do not end on an exciting cliffhanger — close with a sense of calm continuity
"""

REFLECT_PROMPT = """\
#Role: You are a careful scientific editor and narrative quality reviewer \
for a bedtime science podcast aimed at adults.

#Task: Review the following chapter and decide if it meets quality standards.

#Context:
  Story topic: "{topic}"
  This is chapter {chapter_num}.
  Target chapter length: ~{words_per_chapter} words (acceptable range: \
{words_per_chapter_min}–{words_per_chapter_max} words)
  Story so far (for continuity reference):
  ---
  {story_so_far}
  ---
  Chapter to review:
  ---
  {current_chapter_draft}
  ---

#Format: Reply ONLY in one of these two exact formats — nothing else:

  PASSED

  or

  NEEDS_REVISION
  - <specific issue 1>
  - <specific issue 2>

#Goal: Ensure every chapter is scientifically sound, educationally substantive, \
appropriately paced, appropriately calm, and flows naturally from what came before.

#Requirements / Constraints:
- Check scientific accuracy — flag any errors, outdated claims, or misleading simplifications
- Check factual density — flag if the chapter is predominantly atmosphere/imagery with fewer \
  than 2–3 concrete facts, measurements, or named mechanisms; pure mood is not sufficient
- Check tone — it must be soothing and unhurried, suitable for bedtime; flag anything too \
  exciting or intense
- Check continuity — it must connect naturally to the preceding text
- Check pacing / length — count the approximate words in the chapter; flag if it falls \
  outside the acceptable range ({words_per_chapter_min}–{words_per_chapter_max} words); \
  a chapter that is too short will leave dead air, too long will overrun the episode runtime
- Do NOT rewrite the chapter; only identify issues
- Be concise in your feedback — one line per issue
"""

REVISE_CHAPTER_PROMPT = """\
#Role: You are a science narrator revising a chapter based on a reviewer's \
specific feedback. Your revision must fix every flagged issue without \
sacrificing scientific accuracy or introducing new errors.

#Task: Rewrite chapter {chapter_num} of {num_chapters} to address every issue \
raised in the reflection feedback below.

#Topic: The story is about "{topic}" (domain: {domain}).

#Context:
  Chapter title: {title}
  Chapter focus: {summary}
  Target audience: {audience}
  Story so far (for narrative continuity):
  ---
  {story_so_far}
  ---
  Previous draft (the text that was reviewed):
  ---
  {previous_draft}
  ---
  Reviewer feedback (issues you MUST fix):
  ---
  {reflect_feedback}
  ---

#Format: Plain prose only. No title, no headers, no bullet points. \
Target approximately {words_per_chapter} words.

#Tone / Style: {style} — warm and unhurried, suitable for listening while \
relaxed. Analogies should clarify science, not replace it.

#Goal: A revised chapter that fixes every flagged issue and still delivers \
at least 2–3 concrete scientific facts in an accessible, calm way.

#Requirements / Constraints:
- Address each bullet point in the reviewer feedback explicitly
- Each chapter must contain at least 2–3 concrete, accurate scientific facts \
  or mechanisms — do not let atmosphere crowd out substance
- Do not introduce new scientific inaccuracies while fixing old ones
- Do not include the chapter title in your output
- Keep the same narrative position in the story arc — do not jump ahead
- Maintain the calm, soothing tone throughout
"""

POLISH_PROMPT = """\
#Role: You are a copy-editor doing a final light pass on a bedtime science \
story. Your job is surface-level only — you are NOT a rewriter.

#Task: Make minimal edits to improve flow and tonal consistency between \
chapters. Every scientific fact must survive your edit unchanged.

#Topic: Bedtime science story — scientific accuracy is non-negotiable.

#Format: Return only the lightly edited story text. No title, no chapter \
labels, no headers, no commentary. Target approximately {target_total_words} words total.

#Tone / Style: Calm, gentle, and contemplative throughout — a single quiet \
narrator voice. Soften any passage that feels too energetic for bedtime.

#Goal: A seamlessly flowing story where every paragraph still says exactly \
what it said before — just with smoother joins and a more consistent voice.

#Requirements / Constraints:
- PERMITTED edits (surface level only):
  * Add or rephrase a short transition sentence between chapters
  * Replace a word or short phrase to match the narrator's tone
  * Break an overly long sentence into two shorter ones
  * Soften exclamation-style language into calm declarative phrasing
- FORBIDDEN edits (factual integrity):
  * Do not merge two sentences that carry different facts
  * Do not restructure or reorder paragraphs
  * Do not substitute, rephrase, or reinterpret any scientific claim
  * Do not introduce any fact, figure, analogy, or implication not already present
  * Do not delete content — only trim filler words if unavoidable
- If a passage is already good, leave it exactly as written
- When in doubt, do less — a slightly rough join is safer than a rewritten fact

<story>
{joined_chapters}
</story>
"""


# ── SECTION 3: LLMs & Parser ─────────────────────────────────────────────────

# Generation: most capable model for rich, creative story writing and polishing
generation_llm = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview", temperature=0.75
)

# Reflection: fast, analytical model for structured quality review
reflect_llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash", temperature=0.2
)

parser = StrOutputParser()


# ── SECTION 4: Node Functions ────────────────────────────────────────────────


def _story_so_far(state: StoryState) -> str:
    return (
        "\n\n".join(state["completed_chapters"])
        if state["completed_chapters"]
        else "This is the opening chapter — there is no preceding text."
    )


def plan_story(state: StoryState) -> dict:
    """Derive story parameters from duration, then generate the chapter outline."""
    num_chapters, target_total_words, words_per_chapter = derive_story_params(
        state["duration_min"]
    )

    chain = PromptTemplate.from_template(PLAN_PROMPT) | generation_llm | parser
    raw = chain.invoke({
        "topic": state["topic"],
        "domain": state["domain"],
        "audience": state["audience"],
        "style": state["style"],
        "duration_min": state["duration_min"],
        "num_chapters": num_chapters,
        "target_total_words": target_total_words,
        "words_per_chapter": words_per_chapter,
    }).strip()

    # Strip markdown code fences if the model wraps the JSON anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    chapter_plans = _parse_chapter_plans(raw, num_chapters)

    return {
        "num_chapters": num_chapters,
        "target_total_words": target_total_words,
        "words_per_chapter": words_per_chapter,
        "chapter_plans": chapter_plans,
        "current_chapter_index": 0,
        "current_chapter_draft": None,
        "reflect_feedback": None,
        "reflect_passed": None,
        "chapter_rewrite_count": 0,
        "completed_chapters": [],
        "forced_chapters": [],
        "status_message": (
            f"Outline ready: {num_chapters} chapters, "
            f"~{words_per_chapter} words each, "
            f"target {state['duration_min']} min."
        ),
    }


def write_chapter(state: StoryState) -> dict:
    """Write the initial draft of the current chapter (no prior feedback)."""
    idx = state["current_chapter_index"]
    plan = state["chapter_plans"][idx]

    chain = PromptTemplate.from_template(WRITE_CHAPTER_PROMPT) | generation_llm | parser
    draft = chain.invoke({
        "chapter_num": idx + 1,
        "num_chapters": state["num_chapters"],
        "topic": state["topic"],
        "domain": state["domain"],
        "title": plan["title"],
        "summary": plan["summary"],
        "audience": state["audience"],
        "style": state["style"],
        "words_per_chapter": state["words_per_chapter"],
        "story_so_far": _story_so_far(state),
    }).strip()

    return {
        "current_chapter_draft": draft,
        "reflect_feedback": None,   # clear any stale feedback from a previous chapter
        "status_message": f"Chapter {idx + 1}/{len(state['chapter_plans'])} drafted: \"{plan['title']}\"",
    }


def reflect_chapter(state: StoryState) -> dict:
    """Evaluate the current draft for scientific accuracy, tone, and continuity."""
    idx = state["current_chapter_index"]

    target = state["words_per_chapter"]
    chain = PromptTemplate.from_template(REFLECT_PROMPT) | reflect_llm | parser
    content = chain.invoke({
        "chapter_num": idx + 1,
        "topic": state["topic"],
        "words_per_chapter": target,
        "words_per_chapter_min": int(target * 0.75),
        "words_per_chapter_max": int(target * 1.25),
        "current_chapter_draft": state["current_chapter_draft"],
        "story_so_far": _story_so_far(state),
    }).strip()

    passed = content.startswith("PASSED")
    return {
        "reflect_feedback": content,
        "reflect_passed": passed,
        "status_message": (
            f"Chapter {idx + 1} approved."
            if passed
            else f"Chapter {idx + 1} needs revision."
        ),
    }


def iterate_chapter(state: StoryState) -> dict:
    """Increment the revision counter after each revise → reflect cycle."""
    new_count = state["chapter_rewrite_count"] + 1
    idx = state["current_chapter_index"]
    return {
        "chapter_rewrite_count": new_count,
        "status_message": f"Chapter {idx + 1} revision attempt {new_count} complete.",
    }


def revise_chapter(state: StoryState) -> dict:
    """Rewrite the current chapter using the reviewer's specific feedback.

    This is the key difference from write_chapter: the revision prompt explicitly
    includes both the previous draft and the reflect_feedback, so the LLM knows
    exactly what to fix rather than regenerating blindly from scratch.
    """
    idx = state["current_chapter_index"]
    plan = state["chapter_plans"][idx]

    chain = PromptTemplate.from_template(REVISE_CHAPTER_PROMPT) | generation_llm | parser
    revised = chain.invoke({
        "chapter_num": idx + 1,
        "num_chapters": state["num_chapters"],
        "topic": state["topic"],
        "domain": state["domain"],
        "title": plan["title"],
        "summary": plan["summary"],
        "audience": state["audience"],
        "style": state["style"],
        "words_per_chapter": state["words_per_chapter"],
        "story_so_far": _story_so_far(state),
        "previous_draft": state["current_chapter_draft"],
        "reflect_feedback": state["reflect_feedback"],
    }).strip()

    return {
        "current_chapter_draft": revised,
        "status_message": f"Chapter {idx + 1} revised based on feedback.",
    }


def advance_chapter(state: StoryState) -> dict:
    """Commit the current chapter and reset revision state for the next one.

    If reflect_passed is False here, the chapter was force-advanced after exhausting
    retries. Record its index in forced_chapters for later debugging/analysis.
    """
    idx = state["current_chapter_index"]
    completed = list(state["completed_chapters"]) + [state["current_chapter_draft"]]
    next_idx = idx + 1
    total = len(state["chapter_plans"])
    forced = list(state["forced_chapters"])

    was_forced = not state.get("reflect_passed", True)
    if was_forced:
        forced.append(idx)
        status = (
            f"WARNING: Chapter {idx + 1} force-advanced after "
            f"{state['chapter_rewrite_count']} failed revision(s). "
            + (f"Moving to chapter {next_idx + 1}." if next_idx < total else "Proceeding to polish.")
        )
    else:
        status = (
            f"Chapter {idx + 1} approved and committed. "
            + (f"Moving to chapter {next_idx + 1} of {total}." if next_idx < total else "All chapters done. Polishing the full story.")
        )

    return {
        "completed_chapters": completed,
        "forced_chapters": forced,
        "current_chapter_index": next_idx,
        "current_chapter_draft": None,
        "reflect_feedback": None,
        "reflect_passed": None,
        "chapter_rewrite_count": 0,
        "status_message": status,
    }


def polish_story(state: StoryState) -> dict:
    """Final editing pass over the assembled story for consistent tone and flow."""
    joined = "\n\n".join(state["completed_chapters"])

    chain = PromptTemplate.from_template(POLISH_PROMPT) | generation_llm | parser
    polished = chain.invoke({
        "joined_chapters": joined,
        "target_total_words": state["target_total_words"],
    }).strip()

    return {
        "final_story": polished,
        "status_message": "Story complete and polished.",
    }


# ── SECTION 5: Routing ───────────────────────────────────────────────────────


def route_after_reflect(state: StoryState) -> str:
    """After reflection: approved → advance, failed → revise or force-advance if retries exhausted.

    The force-advance decision lives here — after reflection has run — so the last
    revised draft always gets evaluated before we decide to give up on it.
    """
    if state["reflect_passed"]:
        return "advance_chapter"
    if state["chapter_rewrite_count"] >= 2:
        # Retries exhausted: advance_chapter will detect reflect_passed=False and log a warning
        return "advance_chapter"
    return "revise_chapter"


def route_after_iterate(_: StoryState) -> str:
    """After incrementing the counter: always return to reflect_chapter.

    The counter is for bookkeeping only — the decision to stop retrying is made
    in route_after_reflect, after the revised draft has been evaluated.
    """
    return "reflect_chapter"


def route_after_advance(state: StoryState) -> str:
    """After advancing: write the next chapter or move to polish."""
    if state["current_chapter_index"] < len(state["chapter_plans"]):
        return "write_chapter"
    return "polish_story"


# ── SECTION 6: Graph Assembly ────────────────────────────────────────────────

builder = StateGraph(StoryState)

builder.add_node("plan_story", plan_story)
builder.add_node("write_chapter", write_chapter)
builder.add_node("reflect_chapter", reflect_chapter)
builder.add_node("revise_chapter", revise_chapter)
builder.add_node("iterate_chapter", iterate_chapter)
builder.add_node("advance_chapter", advance_chapter)
builder.add_node("polish_story", polish_story)

builder.set_entry_point("plan_story")
builder.add_edge("plan_story", "write_chapter")
builder.add_edge("write_chapter", "reflect_chapter")
builder.add_conditional_edges(
    "reflect_chapter",
    route_after_reflect,
    {
        "revise_chapter": "revise_chapter",
        "advance_chapter": "advance_chapter",
    },
)
builder.add_edge("revise_chapter", "iterate_chapter")
builder.add_conditional_edges(
    "iterate_chapter",
    route_after_iterate,
    {
        "reflect_chapter": "reflect_chapter",
        "advance_chapter": "advance_chapter",
    },
)
builder.add_conditional_edges(
    "advance_chapter",
    route_after_advance,
    {
        "write_chapter": "write_chapter",
        "polish_story": "polish_story",
    },
)
builder.add_edge("polish_story", END)

graph = builder.compile()
