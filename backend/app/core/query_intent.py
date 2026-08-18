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


def query_terms(q: str) -> set[str]:
    """Content words from a query, minus stopwords and single non-digit chars."""
    return {
        t for t in re.findall(r"[a-z0-9]+", q.lower())
        if t not in _STOP and (len(t) >= 2 or t.isdigit())
    }


def lex_bonus(terms: set[str], v) -> float:
    """Bounded lexical bonus for one vehicle given the query terms.

    `v` is any object exposing make/model/ai_segment/body_type/fuel_type/
    ai_lifestyle_tags — the ORM row in production, a stub in tests.
    """
    if not terms:
        return 0.0
    strong = f"{v.make} {v.model}".lower()
    weak = " ".join([
        v.ai_segment or "", v.body_type or "", v.fuel_type or "",
        " ".join(v.ai_lifestyle_tags or []),
    ]).lower()
    s = sum(1 for t in terms if t in strong)
    w = sum(1 for t in terms if t in weak)
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

_CUR = r"(?:€\s*|eur\s*)?"          # optional currency marker
_AMT = r"(\d[\d.,]*)\s*(k|grand)?"  # 20000 · 20,000 · 20.000 · 20k


def _amt(num: str, unit: str | None) -> float:
    """Normalise a captured amount (EU/US separators, k/grand shorthand)."""
    num = num.strip().strip(".,")
    if unit:  # thousands shorthand: "20k" / "20.5k"
        return float(num.replace(",", ".")) * 1000
    return float(num.replace(",", "").replace(".", ""))  # strip thousands seps


def parse_price_intent(query: str) -> tuple[float | None, float | None, str | None]:
    """Return (min_price, max_price, direction) parsed from the query.

    direction is "low" (budget), "high" (luxury) or None, and only nudges
    ordering — the hard bounds come from explicit relational phrases.
    """
    q = query.lower()
    min_p = max_p = None

    m = re.search(r"\b(?:between|from)\s+" + _CUR + _AMT
                  + r"\s*(?:and|to|-|–|—)\s*" + _CUR + _AMT, q)
    if m:
        a, b = _amt(m.group(1), m.group(2)), _amt(m.group(3), m.group(4))
        min_p, max_p = min(a, b), max(a, b)
    else:
        under = re.search(r"\b(?:under|below|less than|up to|no more than|within|"
                          r"at most|cheaper than|max(?:imum)?(?:\s+of)?|"
                          r"budget of)\s+" + _CUR + _AMT, q)
        if under:
            max_p = _amt(under.group(1), under.group(2))
        # (?<!no ) so "no more than X" stays an upper bound, not also a lower one
        over = re.search(r"(?<!no )\b(?:over|above|more than|at least|"
                         r"min(?:imum)?(?:\s+of)?|starting (?:at|from)|north of)\s+"
                         + _CUR + _AMT, q)
        if over:
            min_p = _amt(over.group(1), over.group(2))
        if min_p is None and max_p is None:
            near = re.search(r"\b(?:around|about|approx(?:imately)?|~|near|roughly)"
                             r"\s+" + _CUR + _AMT, q)
            if near:
                c = _amt(near.group(1), near.group(2))
                min_p, max_p = 0.85 * c, 1.15 * c

    toks = set(re.findall(r"[a-z][a-z-]*", q))
    direction = "low" if toks & _BUDGET_LOW else "high" if toks & _BUDGET_HIGH else None
    return min_p, max_p, direction
