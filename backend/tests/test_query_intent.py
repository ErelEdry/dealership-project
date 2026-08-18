"""Unit tests for the pure query-understanding helpers (no I/O)."""

from types import SimpleNamespace

import pytest

from app.core.query_intent import BONUS_CAP, lex_bonus, parse_price_intent, query_terms


# ── parse_price_intent: explicit bounds ──────────────────────
class TestExplicitBounds:
    @pytest.mark.parametrize("q,expected", [
        ("city car under €20k", 20000),
        ("under 20000", 20000),
        ("hatchback below 15k", 15000),
        ("up to €25,000", 25000),
        ("no more than 30k", 30000),
        ("cheaper than 18k", 18000),
        ("budget of 12000", 12000),
        ("at most 22k", 22000),
    ])
    def test_upper_bound(self, q, expected):
        lo, hi, _ = parse_price_intent(q)
        assert hi == expected
        assert lo is None

    @pytest.mark.parametrize("q,expected", [
        ("over €50k", 50000),
        ("above 40000", 40000),
        ("more than 60k", 60000),
        ("at least 30k", 30000),
        ("starting at 25k", 25000),
    ])
    def test_lower_bound(self, q, expected):
        lo, hi, _ = parse_price_intent(q)
        assert lo == expected
        assert hi is None

    def test_between_sets_both(self):
        assert parse_price_intent("SUV between 30k and 40k")[:2] == (30000, 40000)

    def test_between_orders_low_high(self):
        assert parse_price_intent("between 40k and 30k")[:2] == (30000, 40000)

    def test_around_builds_band(self):
        lo, hi, _ = parse_price_intent("around 25k")
        assert lo == pytest.approx(21250)
        assert hi == pytest.approx(28750)


# ── amount normalisation (EU/US separators, shorthand) ───────
class TestAmountParsing:
    @pytest.mark.parametrize("q,expected", [
        ("under €20,000", 20000),   # US thousands separator
        ("under €20.000", 20000),   # EU thousands separator
        ("under 20000", 20000),     # bare
        ("under 20k", 20000),       # k shorthand
        ("under 20.5k", 20500),     # fractional k
        ("under 20 grand", 20000),  # grand shorthand
    ])
    def test_separators_and_shorthand(self, q, expected):
        assert parse_price_intent(q)[1] == expected


# ── qualitative direction (soft ordering) ────────────────────
class TestDirection:
    @pytest.mark.parametrize("q,direction", [
        ("cheap city car", "low"),
        ("budget hatchback", "low"),
        ("affordable ev", "low"),
        ("luxury suv", "high"),
        ("premium sedan", "high"),
        ("fast electric car with long range", None),
    ])
    def test_direction(self, q, direction):
        assert parse_price_intent(q)[2] == direction


# ── false positives: numbers that aren't prices ──────────────
class TestNoFalsePositives:
    def test_plain_query_has_no_constraints(self):
        assert parse_price_intent("reliable family wagon") == (None, None, None)

    def test_seat_count_is_not_a_price(self):
        # "5 seats" has no relational keyword, so it must not become a bound
        assert parse_price_intent("suv with 5 seats") == (None, None, None)


# ── query_terms ──────────────────────────────────────────────
class TestQueryTerms:
    def test_drops_stopwords(self):
        terms = query_terms("cheap fuel efficient city car for a student")
        assert {"fuel", "efficient", "city", "student"} <= terms
        assert not ({"cheap", "for", "a", "car"} & terms)

    def test_keeps_numeric_model_tokens(self):
        assert "500" in query_terms("fiat 500")


# ── lex_bonus ────────────────────────────────────────────────
def _veh(**kw):
    base = dict(
        make="Toyota", model="Corolla", ai_segment="Compact Car",
        body_type="sedan", fuel_type="petrol",
        ai_lifestyle_tags=["Family-friendly"],
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestLexBonus:
    def test_zero_without_terms(self):
        assert lex_bonus(set(), _veh()) == 0.0

    def test_strong_hit_on_make(self):
        assert lex_bonus({"toyota"}, _veh()) == pytest.approx(0.02)

    def test_weak_hit_on_fuel(self):
        assert lex_bonus({"petrol"}, _veh()) == pytest.approx(0.008)

    def test_bonus_is_capped(self):
        v = _veh(ai_lifestyle_tags=["alpha", "beta", "gamma", "delta",
                                    "epsilon", "zeta", "eta", "theta"])
        terms = {"toyota", "corolla", "alpha", "beta", "gamma",
                 "delta", "epsilon", "zeta", "eta", "theta"}
        # 2 strong (0.04) + 8 weak (0.064) = 0.104 → clamped to the cap
        assert lex_bonus(terms, v) == pytest.approx(BONUS_CAP)
