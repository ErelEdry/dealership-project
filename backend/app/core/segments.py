"""
Canonical vehicle-segment vocabulary.
------------------------------------
`ai_segment` was originally free text, which produced 68 near-duplicate values
(`Pickup` vs `Pickup Truck`, `City Car` vs `Supermini` vs `Compact Car`, …) and
made the field unusable as a filter facet.

This module is the single source of truth for the approved segment list. It is
imported by:
  * the enrichment prompt        (constrains what the LLM may emit)
  * the AIEnrichmentOutput schema (snaps LLM output to canonical via validator)
  * any one-off DB normalisation  (maps legacy free-text onto the canonical set)

Keep CANONICAL_SEGMENTS short and non-overlapping — it doubles as the facet list.
"""

from __future__ import annotations

# ── The approved facet vocabulary ────────────────────────────
# "Other" is the last-resort bucket; it is intentionally last.
CANONICAL_SEGMENTS: tuple[str, ...] = (
    "City Car",
    "Supermini",
    "Compact Car",
    "Sedan",
    "Executive Sedan",
    "Estate",
    "Compact SUV",
    "Mid-Size SUV",
    "Full-Size SUV",
    "Coupe",
    "Convertible",
    "Sports Car",
    "Hot Hatch",
    "MPV",
    "Pickup Truck",
    "Van",
    "Luxury Car",
    "Other",
)

FALLBACK_SEGMENT = "Other"

# The list offered to the LLM — every canonical value except the fallback.
PROMPT_SEGMENTS: tuple[str, ...] = tuple(
    s for s in CANONICAL_SEGMENTS if s != FALLBACK_SEGMENT
)

def _flat(s: str) -> str:
    """Lower-case, turn hyphens/slashes into spaces, collapse whitespace.

    Makes matching insensitive to spelling like `Sub-compact` vs `subcompact`
    and `Full-size` vs `full size`.
    """
    out = s.lower().replace("-", " ").replace("/", " ")
    return " ".join(out.split())


# Fast case-insensitive lookup of an exact canonical value.
_CANONICAL_BY_LOWER = {s.lower(): s for s in CANONICAL_SEGMENTS}

# ── Explicit aliases (lower-cased key → canonical value) ─────
# Covers the common legacy / synonym spellings seen in the corpus.
_ALIASES: dict[str, str] = {
    # City Car
    "mini": "City Car",
    "microcar": "City Car",
    "micro car": "City Car",
    "kei car": "City Car",
    "small city car": "City Car",
    # Supermini
    "subcompact": "Supermini",
    "subcompact car": "Supermini",
    "small car": "Supermini",
    "b-segment": "Supermini",
    # Compact Car
    "compact": "Compact Car",
    "compact sedan": "Compact Car",
    "compact hatchback": "Compact Car",
    "hatchback": "Compact Car",
    "hatch": "Compact Car",
    "c-segment": "Compact Car",
    "small family car": "Compact Car",
    # Sedan
    "saloon": "Sedan",
    "midsize sedan": "Sedan",
    "mid-size sedan": "Sedan",
    "mid size sedan": "Sedan",
    "family sedan": "Sedan",
    "d-segment": "Sedan",
    # Executive Sedan
    "full-size sedan": "Executive Sedan",
    "full size sedan": "Executive Sedan",
    "large sedan": "Executive Sedan",
    "luxury sedan": "Executive Sedan",
    "executive car": "Executive Sedan",
    "executive saloon": "Executive Sedan",
    "e-segment": "Executive Sedan",
    # Estate
    "wagon": "Estate",
    "station wagon": "Estate",
    "estate car": "Estate",
    "touring": "Estate",
    "shooting brake": "Estate",
    # Compact SUV
    "crossover": "Compact SUV",
    "compact crossover": "Compact SUV",
    "subcompact suv": "Compact SUV",
    "subcompact crossover": "Compact SUV",
    "small suv": "Compact SUV",
    "suv": "Compact SUV",
    # Mid-Size SUV
    "midsize suv": "Mid-Size SUV",
    "mid size suv": "Mid-Size SUV",
    "mid-size crossover": "Mid-Size SUV",
    # Full-Size SUV
    "large suv": "Full-Size SUV",
    "full size suv": "Full-Size SUV",
    "full-size suv": "Full-Size SUV",
    "7-seat suv": "Full-Size SUV",
    "seven seat suv": "Full-Size SUV",
    "off-roader": "Full-Size SUV",
    "off roader": "Full-Size SUV",
    "off-road suv": "Full-Size SUV",
    "4x4": "Full-Size SUV",
    # Coupe
    "performance coupe": "Coupe",
    "sports coupe": "Coupe",
    "grand tourer": "Coupe",
    "gt": "Coupe",
    "2-door coupe": "Coupe",
    # Convertible
    "roadster": "Convertible",
    "cabriolet": "Convertible",
    "cabrio": "Convertible",
    "spider": "Convertible",
    "spyder": "Convertible",
    "drop-top": "Convertible",
    # Sports Car
    "supercar": "Sports Car",
    "sportscar": "Sports Car",
    "sports car": "Sports Car",
    "hypercar": "Sports Car",
    "muscle car": "Sports Car",
    "pony car": "Sports Car",
    # Hot Hatch
    "warm hatch": "Hot Hatch",
    "performance hatchback": "Hot Hatch",
    "hot hatchback": "Hot Hatch",
    # MPV
    "minivan": "MPV",
    "people carrier": "MPV",
    "people mover": "MPV",
    "multi-purpose vehicle": "MPV",
    # Van
    "panel van": "Van",
    "cargo van": "Van",
    "commercial van": "Van",
    # Pickup Truck
    "pickup": "Pickup Truck",
    "pick-up": "Pickup Truck",
    "pick up": "Pickup Truck",
    "truck": "Pickup Truck",
    "ute": "Pickup Truck",
    # Luxury Car
    "luxury": "Luxury Car",
    "luxury vehicle": "Luxury Car",
    "premium car": "Luxury Car",
}

# Hyphen/slash-insensitive view of the alias table (built once at import).
_ALIASES = {_flat(k): v for k, v in _ALIASES.items()}

# ── Ordered keyword heuristics (first match wins) ────────────
# Fallback for values that are neither exact nor a known alias. Order matters:
# more specific rules first (e.g. size-qualified SUV before bare "suv").
_KEYWORD_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("pickup", "pick-up", "pick up", "ute", "flatbed"), "Pickup Truck"),
    (("full-size suv", "full size suv", "large suv", "off-road", "off road", "7-seat", "seven-seat"), "Full-Size SUV"),
    (("mid-size suv", "midsize suv", "mid size suv"), "Mid-Size SUV"),
    (("suv", "crossover", "cuv"), "Compact SUV"),
    (("hot hatch",), "Hot Hatch"),
    (("estate", "wagon", "touring", "shooting brake"), "Estate"),
    (("minivan", "mpv", "people carrier", "people mover", "multi-purpose"), "MPV"),
    (("panel van", "cargo van", "commercial van", "van"), "Van"),
    (("roadster", "cabriolet", "cabrio", "convertible", "spider", "spyder", "drop-top"), "Convertible"),
    (("supercar", "hypercar", "sports car", "sportscar"), "Sports Car"),
    (("grand tourer", "coupe", "coupé"), "Coupe"),
    (("executive", "full-size sedan", "full size sedan", "large sedan", "luxury sedan"), "Executive Sedan"),
    (("luxury", "premium"), "Luxury Car"),
    (("saloon", "sedan"), "Sedan"),
    (("hatch",), "Compact Car"),
    (("supermini", "subcompact", "sub compact"), "Supermini"),
    (("city car", "microcar", "kei"), "City Car"),
    (("compact",), "Compact Car"),
)


def normalize_segment(raw: str | None) -> str:
    """
    Snap any segment string onto the canonical vocabulary.

    Resolution order: exact canonical match → explicit alias → keyword heuristic
    → FALLBACK_SEGMENT ("Other"). Always returns a value from CANONICAL_SEGMENTS.
    """
    if not raw or not raw.strip():
        return FALLBACK_SEGMENT

    key = _flat(raw)  # hyphen/slash/whitespace-insensitive

    # 1. exact canonical (case-insensitive)
    if key in _CANONICAL_BY_LOWER:
        return _CANONICAL_BY_LOWER[key]

    # 2. explicit alias
    if key in _ALIASES:
        return _ALIASES[key]

    # 3. keyword heuristics (first match wins)
    for needles, canonical in _KEYWORD_RULES:
        if any(_flat(n) in key for n in needles):
            return canonical

    # 4. give up — quarantine into the review bucket
    return FALLBACK_SEGMENT
