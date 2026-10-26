"""
Pure query-understanding helpers for semantic search — no I/O, no heavy imports.

Kept separate from the search route (which pulls in FastEmbed / Qdrant / Redis)
so this logic can be unit-tested in isolation and reused. Two concerns:

  * lexical rerank    — bounded keyword bonus blended into the vector score
  * budget intent     — natural-language price cues → structured constraints
"""

from __future__ import annotations

import re

# ── Lexical rerank weights ───────────────────────────────────
BONUS_CAP = 0.10   # max lexical bonus added to a cosine score (~0.6-0.7)
W_STRONG  = 0.02   # per query-term hit on make/model
W_WEAK    = 0.008  # per query-term hit on segment/body/fuel/tags

_STOP = {
    "a", "an", "the", "for", "and", "or", "with", "of", "to", "in", "on", "my",
    "me", "i", "car", "cars", "vehicle", "vehicles", "looking", "need", "want",
    "would", "like", "good", "nice", "best", "cheap", "affordable", "under",
    "over", "around", "budget", "that", "is", "are",
}


def _tokens(s: str) -> set[str]:
    """Lower-cased alphanumeric tokens ("CR-V" → {"cr", "v"})."""
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def query_terms(q: str) -> set[str]:
    """Content words from a query, minus stopwords and single non-digit chars."""
    return {t for t in _tokens(q) if t not in _STOP and (len(t) >= 2 or t.isdigit())}


def lex_bonus(terms: set[str], v) -> float:
    """Bounded lexical bonus for one vehicle given the query terms.

    `v` is any object exposing make/model/ai_segment/body_type/fuel_type/
    ai_lifestyle_tags — the ORM row in production, a stub in tests.
    """
    if not terms:
        return 0.0
    # Whole-token matches only: a substring test let "ev" hit "chevrolet",
    # "3" hit "mazda3" and "eco" hit "economical".
    strong = _tokens(f"{v.make} {v.model}")
    weak = _tokens(" ".join([
        v.ai_segment or "", v.body_type or "", v.fuel_type or "",
        " ".join(v.ai_lifestyle_tags or []),
    ]))
    s = len(terms & strong)
    w = len(terms & weak)
    return min(BONUS_CAP, W_STRONG * s + W_WEAK * w)


# ── Budget intent ────────────────────────────────────────────
# Turn natural-language price cues into structured constraints, so "cheap city
# car" and "under €20k" actually rank by euros instead of meaning alone.
# Explicit relational amounts → hard price filter; a bare qualitative word →
# only a soft ordering preference (never a hard cap, so it can't empty results).

_BUDGET_LOW = {
    "cheap", "cheapest", "cheaper", "budget", "affordable", "inexpensive",
    "economical", "economy", "bargain", "low-cost", "lowcost", "value",
}
_BUDGET_HIGH = {
    "luxury", "luxurious", "premium", "high-end", "upscale", "expensive",
    "exclusive", "flagship", "top-tier", "prestige",
}

# Numbers followed by one of these are specs, not prices ("50000 km", "7 seats").
_NON_PRICE_UNIT = (r"(?:km|kms|kilomet\w*|mi|miles?|mileage|years?|yrs?|seats?|"
                   r"seater|doors?|hp|bhp|kw|cc|owners?)\b")
_YEAR_RANGE = (1990, 2035)  # a bare number in here is a model year, not a price
_MIN_BARE_PRICE = 1000      # bare amounts below this ("under 5") aren't prices


def _amt_re(i: int) -> str:
    """Amount pattern with named groups cur{i} / num{i} / unit{i}.

    Matches 20000 · 20,000 · 20.000 · €20k · 20 grand. The number may not be cut
    short ("50,000" can't match as "50"), `k` must be a whole word (so "km" is
    not "k"), and a trailing non-price unit rejects the match outright.
    """
    return (rf"(?P<cur{i}>€|eur\b)?\s*"
            rf"(?P<num{i}>\d(?:[\d.,]*\d)?)(?![.,]?\d)"
            rf"(?:\s*(?P<unit{i}>k|grand)\b)?"
            rf"(?!\s*{_NON_PRICE_UNIT})")


def _amt(num: str, unit: str | None) -> float:
    """Normalise a captured amount (EU/US separators, k/grand shorthand)."""
    num = num.strip().strip(".,")
    if unit:  # thousands shorthand: "20k" / "20.5k"
        return float(num.replace(",", ".")) * 1000
    return float(num.replace(",", "").replace(".", ""))  # strip thousands seps


def _price(m: re.Match, i: int) -> float | None:
    """The amount captured as group set `i`, or None if it isn't a price.

    Without a currency marker or k/grand shorthand, a bare number that looks
    like a model year ("from 2018 to 2022") or is too small to be a price
    ("under 5 years old") is ignored.
    """
    unit = m.group(f"unit{i}")
    value = _amt(m.group(f"num{i}"), unit)
    if m.group(f"cur{i}") or unit:
        return value
    if _YEAR_RANGE[0] <= value <= _YEAR_RANGE[1] or value < _MIN_BARE_PRICE:
        return None
    return value


def _first_price(pattern: str, q: str) -> float | None:
    """First price captured by `pattern` (group set 0) in the query."""
    for m in re.finditer(pattern, q):
        value = _price(m, 0)
        if value is not None:
            return value
    return None


def parse_price_intent(query: str) -> tuple[float | None, float | None, str | None]:
    """Return (min_price, max_price, direction) parsed from the query.

    direction is "low" (budget), "high" (luxury) or None, and only nudges
    ordering — the hard bounds come from explicit relational phrases.
    """
    q = query.lower()
    min_p = max_p = None

    for m in re.finditer(r"\b(?:between|from)\s+" + _amt_re(0)
                         + r"\s*(?:and|to|-|–|—)\s*" + _amt_re(1), q):
        a, b = _price(m, 0), _price(m, 1)
        if a is not None and b is not None:
            min_p, max_p = min(a, b), max(a, b)
            break
    else:
        max_p = _first_price(r"\b(?:under|below|less than|up to|no more than|within|"
                             r"at most|cheaper than|max(?:imum)?(?:\s+of)?|"
                             r"budget of)\s+" + _amt_re(0), q)
        # (?<!no ) so "no more than X" stays an upper bound, not also a lower one
        min_p = _first_price(r"(?<!no )\b(?:over|above|more than|at least|"
                             r"min(?:imum)?(?:\s+of)?|starting (?:at|from)|north of)\s+"
                             + _amt_re(0), q)
        if min_p is None and max_p is None:
            c = _first_price(r"(?:\b(?:around|about|approx(?:imately)?|near|roughly)|~)"
                             r"\s*" + _amt_re(0), q)
            if c is not None:
                min_p, max_p = 0.85 * c, 1.15 * c

    toks = set(re.findall(r"[a-z][a-z-]*", q))
    direction = "low" if toks & _BUDGET_LOW else "high" if toks & _BUDGET_HIGH else None
    return min_p, max_p, direction
