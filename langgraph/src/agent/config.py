"""Canonical audience registry — single source of truth for all per-audience parameters.

Add a new audience here and every dependent (graph, TTS, frontend bg-mode) picks it up
automatically. Never hardcode audience strings or per-audience tables elsewhere.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AudienceSpec:
    name:                  str
    wpm:                   int         # words-per-minute for duration estimation
    tts_speed:             float       # TTS playback speed
    max_words_per_chapter: int | None  # None = no cap
    max_chapters:          int
    bg_mode:               str         # frontend background scene key


AUDIENCE_CATALOG: list[AudienceSpec] = [
    AudienceSpec("curious adults",       wpm=170, tts_speed=0.80, max_words_per_chapter=None, max_chapters=6, bg_mode="stars"),
    AudienceSpec("science enthusiasts",  wpm=170, tts_speed=0.80, max_words_per_chapter=None, max_chapters=6, bg_mode="stars"),
    AudienceSpec("children (ages 4–6)",  wpm=155, tts_speed=0.70, max_words_per_chapter=650,  max_chapters=4, bg_mode="dreamy"),
    AudienceSpec("children (ages 7–12)", wpm=160, tts_speed=0.75, max_words_per_chapter=1000, max_chapters=5, bg_mode="galaxy"),
    AudienceSpec("children (ages 13+)",  wpm=165, tts_speed=0.80, max_words_per_chapter=None, max_chapters=6, bg_mode="galaxy"),
]

AUDIENCES: list[str] = [a.name for a in AUDIENCE_CATALOG]

_AUDIENCE_BY_NAME: dict[str, AudienceSpec] = {a.name: a for a in AUDIENCE_CATALOG}

_DEFAULT = AudienceSpec(
    name="", wpm=170, tts_speed=0.80, max_words_per_chapter=None, max_chapters=6, bg_mode="stars"
)


def get_audience(name: str) -> AudienceSpec:
    """Return the spec for name, or the default spec if name is unrecognised."""
    return _AUDIENCE_BY_NAME.get(name, _DEFAULT)
