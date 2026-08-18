"""Unit tests for the deterministic price-regeneration model."""

from scripts.regenerate_prices import acquisition_for, fix_summary, price_for


class TestPriceFor:
    def test_deterministic(self):
        args = ("SYNVIN0001", "Toyota", 2020, "petrol", "Compact Car", 50000)
        assert price_for(*args) == price_for(*args)

    def test_rounded_to_250(self):
        p = price_for("SYNVIN0002", "Bmw", 2019, "electric", "Executive Sedan", 30000)
        assert p % 250 == 0

    def test_respects_floor(self):
        # ancient, high-mileage city car — must not drop below the €5,000 floor
        p = price_for("SYNVIN0003", "Fiat", 2000, "petrol", "City Car", 380000)
        assert p >= 5000

    def test_segment_ordering(self):
        # same VIN/inputs, different segment → luxury outranks a city car
        common = dict(year=2022, fuel="petrol", mileage=20000)
        city = price_for("SYNVIN0004", "Toyota", segment="City Car", **common)
        lux = price_for("SYNVIN0004", "Toyota", segment="Luxury Car", **common)
        assert lux > city

    def test_depreciation_newer_costs_more(self):
        new = price_for("SYNVINX", "Toyota", 2024, "petrol", "Compact SUV", 20000)
        old = price_for("SYNVINX", "Toyota", 2005, "petrol", "Compact SUV", 20000)
        assert new > old


class TestAcquisitionFor:
    def test_below_sale_price(self):
        assert 0 < acquisition_for("SYNVIN0005", 30000) < 30000

    def test_deterministic(self):
        assert acquisition_for("SYNVIN0005", 30000) == acquisition_for("SYNVIN0005", 30000)


class TestFixSummary:
    def test_dollar_figure_rewritten_to_euro(self):
        out = fix_summary("The 2025 Fiat Panda is priced at $19,500.", 14500)
        assert "$" not in out
        assert "€14,500" in out

    def test_noop_when_no_currency_figure(self):
        s = "A tidy hatchback with low mileage."
        assert fix_summary(s, 14500) == s

    def test_none_passthrough(self):
        assert fix_summary(None, 14500) is None
