"""Unit tests for the canonical segment normaliser."""

import pytest

from app.core.segments import CANONICAL_SEGMENTS, FALLBACK_SEGMENT, normalize_segment


def test_exact_canonical_passthrough():
    assert normalize_segment("Compact SUV") == "Compact SUV"


def test_case_and_hyphen_insensitive():
    assert normalize_segment("compact suv") == "Compact SUV"
    assert normalize_segment("Full-Size SUV") == "Full-Size SUV"


@pytest.mark.parametrize("raw,expected", [
    ("hatchback", "Compact Car"),
    ("crossover", "Compact SUV"),
    ("pickup", "Pickup Truck"),
    ("saloon", "Sedan"),
    ("wagon", "Estate"),
    ("cabriolet", "Convertible"),
    ("minivan", "MPV"),
])
def test_aliases(raw, expected):
    assert normalize_segment(raw) == expected


def test_keyword_heuristic_fallthrough():
    # neither exact nor alias — resolved by keyword rule ("off road" → full-size)
    assert normalize_segment("large off-road SUV") == "Full-Size SUV"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_empty_inputs_fall_back(raw):
    assert normalize_segment(raw) == FALLBACK_SEGMENT


def test_unknown_falls_back():
    assert normalize_segment("spaceship") == FALLBACK_SEGMENT


@pytest.mark.parametrize("raw", ["SUV", "weird value", "muscle car", None, "Sports Car"])
def test_always_returns_canonical_value(raw):
    assert normalize_segment(raw) in CANONICAL_SEGMENTS
