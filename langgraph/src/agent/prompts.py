"""All LLM prompt templates for the NightyNight story pipeline."""

# ── Adult / general: plan ─────────────────────────────────────────────────────

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

# ── Children (4–6): plan ──────────────────────────────────────────────────────

PLAN_PROMPT_4_6 = """\
#Role: You are a gentle bedtime storyteller creating a simple science story \
for children aged 4–6.

#Task: Create a {num_chapters}-chapter outline. \
Each chapter explains exactly ONE simple idea.

#Topic: {topic}

#Format: Return ONLY a valid JSON array with exactly {num_chapters} objects. \
No markdown fences, no extra text.
[
  {{"title": "...", "summary": "..."}},
  ...
]

#Rules:
- Each chapter title must be short and concrete (e.g. "The Tiny Seed", "The First Light")
- Each summary must be ONE sentence only
- Each summary must describe one simple thing a child can imagine
- Each summary must be understandable without any science background
- Do not include cause-and-effect chains in summaries
- Do not include invisible mechanisms
- Use one familiar image per chapter
- Allowed images: seed, balloon, blanket, toy, candle, stars, warm bread, \
  puddle, garden, nightlight
- FORBIDDEN in summaries: atoms, particles, molecules, gravity, fusion, \
  radiation, plasma, hydrogen, helium, elements, expansion, gas cloud, \
  nucleosynthesis, decoupling, light-travel, orbit, nebula, density, matter

#Bad summary: "The universe cooled so tiny pieces could join together and let light travel."
#Good summary: "Long ago, everything was tucked into a tiny seed."

#Arc: A familiar beginning → one gentle change → one simple wonder → safe sleepy close
"""

# ── Children (7–12): plan ─────────────────────────────────────────────────────

PLAN_PROMPT_7_12 = """\
#Role: You are a science storyteller creating a bedtime story for children \
aged 7–12. Science is real and accurate, explained through wonder and analogy.

#Task: Create a {num_chapters}-chapter outline for a bedtime science story.

#Topic: {topic}
Words per chapter: ~{words_per_chapter}

#Format: Return ONLY a valid JSON array with exactly {num_chapters} objects. \
No markdown fences, no extra text.
[
  {{"title": "...", "summary": "..."}},
  ...
]

#Rules:
- Each chapter covers 1–2 science ideas — not a full mechanism chain
- Summaries must be understandable to a curious 10-year-old
- Use concrete images and everyday analogies
- Arc: wonder → discovery → one key fact → calm close
"""

# ── Adult / general: chapter ──────────────────────────────────────────────────

WRITE_CHAPTER_PROMPT = """\
#Role: You are a science narrator with dual expertise: you understand the \
science deeply, and you know how to explain it in a calm, unhurried way \
that is pleasant to listen to while drifting toward sleep.

#Task: Write chapter {chapter_num} of {num_chapters} of the story.

#Topic: The story is about "{topic}" (domain: {domain}).

#Full Story Outline (for narrative awareness — do NOT skip ahead or behind):
{full_outline}

#This Chapter:
  Title: {title}
  Focus: {summary}
  Target audience: {audience}

#Format: Plain prose only. No title, no headers, no bullet points. \
Target approximately {words_per_chapter} words \
(acceptable range: {words_min}–{words_max} words).

#Tone / Style: {style} — warm and unhurried. Short sentences. Natural pauses. \
Analogies drawn from everyday life to make abstract concepts land clearly.

#Goal: Deliver the scientific content in this chapter's focus area in a way \
that is genuinely informative AND easy to absorb while relaxed. \
The listener should remember at least one concrete fact from this chapter.

#Requirements / Constraints:
Factual content:
- Each chapter must convey 2–3 real scientific ideas — not just mood or imagery
- Always describe a phenomenon in plain, everyday language first before naming it
- Audience-specific language rules for "{audience}":
  * "curious adults" or "science enthusiasts": you may introduce the technical \
    name as an optional label after the plain description
  * "general public": skip technical names entirely, stay with plain descriptions
  * "children (ages 13+)": treat like "general public" but add more wonder and \
    narrative energy; one or two technical terms per chapter are fine if explained clearly
- Do not invent specific numbers, percentages, or historical lab procedures; \
  use scale instead ("millions of years", "a few degrees warmer", "roughly half")
- Analogies and atmosphere should serve the science, not replace it

Audio / narration quality:
- Write for listening, not reading — a listener cannot re-read a sentence
- Avoid long nested sentences; break dense cause-and-effect chains into two or three shorter ones
- Prefer one main idea per paragraph; do not stack two explanations back to back
- After a technical point, insert a soft transition before moving to the next idea
- Do not use "firstly", "secondly", "finally", or any list-like transitions
- Do not include the chapter title in your output
- Do not end on an exciting cliffhanger — close with a sense of calm continuity

Narrative continuity:
- Connect naturally to the chapter before and after yours per the outline above
- Do not overlap scientific content already covered by adjacent chapters

Self-check before finishing — your output MUST:
✓ Contain 2–3 distinct real scientific facts (not just atmosphere)
✓ Fall within {words_min}–{words_max} words
✓ Flow naturally from the preceding chapter and into the next
✓ End calmly without a cliffhanger
✗ Do NOT invent specific figures you cannot verify
✗ Do NOT include the chapter title
"""

# ── Children (4–6): chapter ───────────────────────────────────────────────────

WRITE_CHAPTER_PROMPT_4_6 = """\
#Role: You are a gentle bedtime storyteller. You know the science deeply, \
but for a 4–6 year old you share only the simplest, warmest part of the idea.

#Task: Write chapter {chapter_num} of {num_chapters}.

#Topic: "{topic}"
#This Chapter:
  Title: {title}
  Focus: {summary}

#Format: Plain prose only. No title. No headers. No bullet points. \
Target {words_per_chapter} words (range: {words_min}–{words_max}).

#Core rule: Explain exactly ONE science idea in this chapter. \
Do not explain how it works in detail. \
Do not explain what happens before or after this chapter.

#Language rules:
- Use very simple words — mostly 1–2 syllable words a kindergartner knows
- Most sentences must be under 10 words
- One idea per sentence
- One main image for the whole chapter — do NOT mix many analogies in one chapter
- Do not use metaphor chains (cycling through multiple comparisons: \
  e.g. first a seed, then a balloon, then soup, then dust — all in one chapter)
- Do not use elegant adult phrasing
- Do not use long cause-and-effect chains

#Word-level guidance: \
If a word sounds like it belongs in a textbook or encyclopedia, replace it. \
Use the simplest everyday word that carries the same meaning. \
Where you would normally name a technical concept, describe what it \
looks or feels like to a child instead.

#Allowed familiar images: seed, balloon, blanket, cookie, soup, toy, puppy, \
garden, moon, stars, warm bread, puddle, nightlight

#Forbidden patterns:
- Do not explain invisible mechanisms
- Do not stack two explanations back to back
- Do not list multiple facts
- Do not summarize the whole story
- Do not jump to future chapters

#Good example:
"The tiny seed grew bigger.
It made more room.
Room for stars.
Room for moons.
Room for sleepy children."

#Bad example:
"As everything cooled, tiny pieces joined together and light could travel freely."

#Emotional target: safe, cozy, curious, sleepy

#Ending: End with comfort, not suspense. The final sentence should feel soft and safe.

#Self-check — if any answer is NO, rewrite before outputting:
✓ Only ONE science idea?
✓ Avoided textbook words (used child-friendly descriptions instead)?
✓ One main image, not a chain of analogies?
✓ Most sentences under 10 words?
✓ Feels like a bedtime story, not a lesson?
✓ Ends calmly?
"""

# ── Children (7–12): chapter ──────────────────────────────────────────────────

WRITE_CHAPTER_PROMPT_7_12 = """\
#Role: You are a science storyteller writing a bedtime chapter for children \
aged 7–12. Science is real and accurate, explained through wonder and analogy.

#Task: Write chapter {chapter_num} of {num_chapters}.

#Topic: "{topic}"
#This Chapter: {title} — {summary}

#Story arc (context only — do not copy or jump ahead):
{full_outline}

#Format: Plain prose. No title. No headers. \
Target {words_per_chapter} words (range: {words_min}–{words_max}).

#Science: 1–2 ideas per chapter. One easy technical term allowed \
if explained immediately in plain words.

#Style: Short sentences. Everyday analogies. Wonder and curiosity. \
End calmly — no cliffhanger.

#Self-check:
✓ 1–2 ideas  ✓ {words_min}–{words_max} words  ✓ calm ending
"""

# ── Final polish ──────────────────────────────────────────────────────────────

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

# ── Children (4–6): polish ────────────────────────────────────────────────────

POLISH_PROMPT_4_6 = """\
#Role: You are a gentle copy-editor for a bedtime science story for children \
ages 4–6. Your job is surface-level only — you are NOT a rewriter.

#Task: Make only tiny edits for flow. Do not make the story more advanced.

#Hard rules:
- Keep very short sentences
- Keep simple words — do not upgrade language to sound more elegant or literary
- Do not add new science or new facts
- Do not add abstract or textbook-style words
- Do not add new analogies
- Do not introduce cause-and-effect explanations that were not already there
- If a word sounds like it belongs in an encyclopedia, replace it with \
  a simpler everyday word — do not let it through

#Permitted edits:
- Fix awkward transitions between chapters
- Break long sentences into shorter ones
- Remove repeated filler words
- Make the ending feel calmer and softer

#Forbidden edits:
- Do not add explanations
- Do not merge two ideas into one sentence
- Do not add new facts or implications
- Do not increase complexity in any way

Return only the edited story. No title, no headers, no commentary.

<story>
{joined_chapters}
</story>
"""

# ── Selectors ─────────────────────────────────────────────────────────────────

def select_plan_prompt(audience: str) -> str:
    if audience == "children (ages 4–6)":
        return PLAN_PROMPT_4_6
    if audience == "children (ages 7–12)":
        return PLAN_PROMPT_7_12
    return PLAN_PROMPT


def select_chapter_prompt(audience: str) -> str:
    if audience == "children (ages 4–6)":
        return WRITE_CHAPTER_PROMPT_4_6
    if audience == "children (ages 7–12)":
        return WRITE_CHAPTER_PROMPT_7_12
    return WRITE_CHAPTER_PROMPT


def select_polish_prompt(audience: str) -> str:
    if audience == "children (ages 4–6)":
        return POLISH_PROMPT_4_6
    return POLISH_PROMPT


# ── StoryGuard revision ───────────────────────────────────────────────────────

REVISION_PROMPT = """\
#Role: You are revising a bedtime science story.

#Target audience:
{audience}

#Revision instruction:
{revision_instruction}

#Original story:
{story}

#Format:
Return only the revised story text. No title, no headers, no commentary.\
"""
