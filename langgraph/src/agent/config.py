"""Canonical constants shared by graph nodes, prompt selectors, and the API layer.

Import from here — never hardcode these strings in individual modules.
"""

# Valid audience identifiers. Order matches the UI dropdown.
AUDIENCES: list[str] = [
    "curious adults",
    "science enthusiasts",
    "children (ages 4–6)",
    "children (ages 7–12)",
    "children (ages 13+)",
]
