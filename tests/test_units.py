"""Property tests for money and count parsing.

These cover the operator properties the product contract requires: unit round
trips, locale aware decimal parsing, missing value propagation, exact decimal
arithmetic for money, and the refusal to read a dimension as a count.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from skillfoundry_domain.units import (
    COUNT_NOUNS,
    DIMENSION_UNITS,
    Locale,
    Money,
    ParseStatus,
    parse_count,
    parse_money,
)


def test_money_arithmetic_is_exact_not_binary_float():
    # 0.1 + 0.2 in binary floating point is not 0.3. Money must not behave
    # that way, because catalog prices are summed across thousands of rows.
    float_total = 0.0
    decimal_total = Decimal("0")
    for _ in range(10):
        float_total += 0.1
        decimal_total += parse_money("0.1", "USD", Locale.US).value.amount
    assert float_total != 1.0, "binary float accumulation drifts, which is the problem"
    assert decimal_total == Decimal("1.0")


def test_unit_price_division_is_exact_when_it_divides_evenly():
    price = parse_money("120", "USD", Locale.US).value
    unit, rounded = price.per_unit(12)
    assert unit == Money(Decimal("10.0000"), "USD")
    assert rounded is False


def test_unit_price_division_flags_rounding_when_inexact():
    price = parse_money("100", "USD", Locale.US).value
    unit, rounded = price.per_unit(3)
    assert unit.amount == Decimal("33.3333")
    assert rounded is True


def test_unit_price_round_trip_multiplies_back_within_rounding():
    price = parse_money("99.99", "USD", Locale.US).value
    unit, rounded = price.per_unit(20)
    assert rounded is False
    assert unit.amount * 20 == price.amount


def test_per_unit_rejects_a_non_positive_count():
    price = parse_money("10", "USD", Locale.US).value
    with pytest.raises(ValueError):
        price.per_unit(0)


@pytest.mark.parametrize(
    "raw,locale,expected",
    [
        ("1,234.56", Locale.US, Decimal("1234.56")),
        ("1.234,56", Locale.EU, Decimal("1234.56")),
        ("$1,000", Locale.US, Decimal("1000")),
        ("0.85", Locale.US, Decimal("0.85")),
        ("0,85", Locale.EU, Decimal("0.85")),
    ],
)
def test_locale_aware_decimal_parsing(raw, locale, expected):
    parsed = parse_money(raw, "USD", locale)
    assert parsed.status is ParseStatus.OK
    assert parsed.value.amount == expected


def test_the_same_string_means_different_numbers_under_each_locale():
    # This is why the convention is declared per supplier and never guessed.
    us = parse_money("1.234", "USD", Locale.US).value.amount
    eu = parse_money("1.234", "EUR", Locale.EU).value.amount
    assert us == Decimal("1.234")
    assert eu == Decimal("1234")
    assert us != eu


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_missing_price_propagates_as_missing_not_zero(raw):
    parsed = parse_money(raw, "USD", Locale.US)
    assert parsed.status is ParseStatus.MISSING
    assert parsed.value is None


@pytest.mark.parametrize("raw", ["abc", "n/a", "-"])
def test_unparseable_price_is_ambiguous_not_zero(raw):
    assert parse_money(raw, "USD", Locale.US).status is ParseStatus.AMBIGUOUS


def test_negative_price_is_refused():
    assert parse_money("-5.00", "USD", Locale.US).status is ParseStatus.AMBIGUOUS


@pytest.mark.parametrize("unit", sorted(DIMENSION_UNITS))
def test_a_number_carrying_any_dimension_unit_is_never_a_count(unit):
    parsed = parse_count(f"12 {unit}")
    assert parsed.status is ParseStatus.AMBIGUOUS
    assert parsed.value is None
    assert unit in parsed.reason


@pytest.mark.parametrize("noun", sorted(COUNT_NOUNS))
def test_a_number_carrying_a_count_noun_is_a_count(noun):
    parsed = parse_count(f"12 {noun}")
    assert parsed.status is ParseStatus.OK
    assert parsed.value == 12


def test_dimension_and_count_vocabularies_do_not_overlap():
    assert not (DIMENSION_UNITS & COUNT_NOUNS)


@pytest.mark.parametrize("raw", ["12", " 12 ", "12"])
def test_a_bare_integer_is_a_count(raw):
    assert parse_count(raw).value == 12


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_missing_pack_size_propagates_as_missing(raw):
    assert parse_count(raw).status is ParseStatus.MISSING


@pytest.mark.parametrize("raw", ["0", "assorted", "12-24", "many"])
def test_unusable_pack_sizes_are_ambiguous(raw):
    assert parse_count(raw).status is ParseStatus.AMBIGUOUS


def test_count_parsing_is_idempotent_on_its_own_output():
    once = parse_count("12 pk")
    twice = parse_count(str(once.value))
    assert once.value == twice.value == 12


def test_lenient_mode_accepts_a_dimension_which_is_why_it_is_unsafe():
    strict = parse_count("12 mm")
    lenient = parse_count("12 mm", lenient=True)
    assert strict.status is ParseStatus.AMBIGUOUS
    assert lenient.status is ParseStatus.OK
    assert lenient.value == 12
