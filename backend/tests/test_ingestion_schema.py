"""Unit tests for RawVehicle ingestion validation + coercion."""

import pytest
from pydantic import ValidationError

from app.schemas.inventory import EnrichedVehicle, RawVehicle


def _row(**kw):
    base = dict(
        vin="synabc1234567", dealer_id="DEALER_001", make="toyota",
        model="corolla", year=2020, mileage=50000, price=25000.0,
    )
    base.update(kw)
    return base


class TestCoercion:
    def test_vin_is_stripped_and_uppercased(self):
        assert RawVehicle(**_row(vin="  synabc9999999 ")).vin == "SYNABC9999999"

    @pytest.mark.parametrize("make,model", [
        ("BMW", "X5"), ("Toyota", "RAV4"), ("Honda", "CR-V"), ("Mazda", "CX-30"),
        ("Mercedes-Benz", "GLE"), ("Volvo", "XC60"), ("Ford", "F-150"),
    ])
    def test_make_and_model_keep_their_casing(self, make, model):
        # .title() used to store Bmw / Rav4 / Cr-V / Gle / Xc60.
        v = RawVehicle(**_row(make=make, model=model))
        assert (v.make, v.model) == (make, model)

    def test_make_and_model_are_stripped(self):
        v = RawVehicle(**_row(make="  BMW ", model=" X5  "))
        assert (v.make, v.model) == ("BMW", "X5")

    def test_qdrant_payload_has_case_insensitive_make_key(self):
        v = EnrichedVehicle(**RawVehicle(**_row(make="BMW")).model_dump())
        meta = v.qdrant_metadata()
        assert meta["make"] == "BMW"
        assert meta["make_key"] == "bmw"

    def test_price_parsed_from_currency_string(self):
        assert RawVehicle(**_row(price="$32,500")).price == 32500.0

    def test_mileage_parsed_from_string(self):
        assert RawVehicle(**_row(mileage="12,000 km")).mileage == 12000

    def test_enums_stored_as_values(self):
        v = RawVehicle(**_row(fuel_type="electric", body_type="suv",
                              stock_status="reserved"))
        assert (v.fuel_type, v.body_type, v.stock_status) == (
            "electric", "suv", "reserved")


class TestConstraints:
    def test_price_must_be_positive(self):
        with pytest.raises(ValidationError):
            RawVehicle(**_row(price=0))

    def test_year_below_1980_rejected(self):
        with pytest.raises(ValidationError):
            RawVehicle(**_row(year=1900))

    def test_seats_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            RawVehicle(**_row(seats=99))


class TestAnomalyFlags:
    def test_flags_high_mileage(self):
        v = RawVehicle(**_row(mileage=500000))
        assert v._anomaly_flags  # non-empty list

    def test_clean_row_has_no_flags(self):
        v = RawVehicle(**_row(mileage=50000, price=25000))
        assert v._anomaly_flags == []
