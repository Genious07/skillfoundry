"""Exact decimal money, locale aware number parsing, and strict count parsing.

Two rules drive this module.

Money never touches binary floating point. Catalog prices are financial values
and a unit price derived from a carton price must be reproducible to the cent.

A count is not just a number. The single most damaging failure in catalog
normalization is treating a dimension as a pack size, so that a 12 mm bolt
priced per item gets its price divided by twelve. Parsing therefore refuses to
guess: a bare integer is a count, an integer carrying a count noun is a count,
and an integer carrying a dimension unit is ambiguous and must be reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from enum import Enum
from typing import Final

# Unit price keeps four decimal places. Catalog unit prices routinely need more
# precision than the cent, for example a carton of 3 at 100.00, and rounding to
# two would silently lose money across a large order.
UNIT_PRICE_EXPONENT: Final[Decimal] = Decimal("0.0001")
DISPLAY_EXPONENT: Final[Decimal] = Decimal("0.01")


class Locale(str, Enum):
    """Explicit decimal convention for a supplier feed.

    There is no reliable way to infer this per row. The string "1.234" is one
    thousand two hundred thirty four under EU convention and one point two
    three four under US convention. Guessing produces a thousandfold error, so
    the convention is declared per supplier and never inferred.
    """

    US = "us"
    EU = "eu"


class ParseStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def per_unit(self, count: int) -> tuple["Money", bool]:
        """Divide a pack price into a unit price.

        Returns the unit price and whether rounding was applied, because an
        inexact division is information the reviewer needs rather than
        something to hide.
        """
        if count <= 0:
            raise ValueError("count must be positive")
        if not self.amount.is_finite() or self.amount < 0:
            raise ValueError("money must be finite and nonnegative")
        with localcontext() as context:
            context.prec = max(
                64, len(self.amount.as_tuple().digits) + len(str(count)) + 16
            )
            raw = self.amount / Decimal(count)
            quantized = raw.quantize(UNIT_PRICE_EXPONENT, rounding=ROUND_HALF_UP)
            return Money(quantized, self.currency), quantized != raw


@dataclass(frozen=True)
class ParsedMoney:
    status: ParseStatus
    value: Money | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ParsedCount:
    status: ParseStatus
    value: int | None = None
    reason: str | None = None


# Suffixes that genuinely denote a quantity of items.
COUNT_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "pk",
        "pack",
        "packs",
        "ct",
        "count",
        "pc",
        "pcs",
        "piece",
        "pieces",
        "x",
        "ea",
        "each",
    }
)

# Suffixes that denote a physical dimension, mass, or volume. A number carrying
# one of these is never a pack size.
DIMENSION_UNITS: Final[frozenset[str]] = frozenset(
    {
        "mm",
        "cm",
        "m",
        "in",
        "inch",
        "inches",
        "ft",
        "thou",
        "g",
        "kg",
        "mg",
        "lb",
        "lbs",
        "oz",
        "ml",
        "l",
        "cl",
        "gal",
        "qt",
        "pt",
        "v",
        "w",
        "kw",
        "a",
        "ma",
        "hz",
        "khz",
        "nm",
        "um",
    }
)

_MONEY_STRIP = re.compile(r"[^\d.,\-]")
_COUNT_PATTERN = re.compile(r"^(\d+)\s*([a-z]*)$")


def parse_money(raw: object, currency: str, locale: Locale) -> ParsedMoney:
    """Parse a supplier price string into exact decimal money."""
    if raw is None:
        return ParsedMoney(ParseStatus.MISSING, reason="price is absent")
    text = str(raw).strip()
    if not text:
        return ParsedMoney(ParseStatus.MISSING, reason="price is empty")

    if len(text) > 80:
        return ParsedMoney(
            ParseStatus.AMBIGUOUS, reason="price exceeds supported length"
        )
    # Accept a whole numeric token, with an optional matching currency prefix.
    # Removing arbitrary characters would turn 1e3 into 13 and 10/12 into 1012.
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
    for prefix in (currency, symbols.get(currency, "")):
        if prefix and text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    pattern = (
        r"(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]{1,8})?"
        if locale is Locale.EU
        else r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,8})?"
    )
    if re.fullmatch(pattern, text) is None or sum(c.isdigit() for c in text) > 24:
        return ParsedMoney(
            ParseStatus.AMBIGUOUS,
            reason="price is not a supported complete numeric token",
        )
    normalized = (
        text.replace(".", "").replace(",", ".")
        if locale is Locale.EU
        else text.replace(",", "")
    )

    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return ParsedMoney(
            ParseStatus.AMBIGUOUS, reason=f"cannot parse {text!r} as a number"
        )

    if amount < 0:
        return ParsedMoney(ParseStatus.AMBIGUOUS, reason=f"negative price {text!r}")
    return ParsedMoney(ParseStatus.OK, value=Money(amount, currency))


def parse_count(raw: object, lenient: bool = False) -> ParsedCount:
    """Parse a pack size, refusing to read a dimension as a count.

    Lenient mode extracts the leading integer regardless of what unit follows
    it. This is the mistake a naive proposal makes, and it is supported here so
    that such a proposal can be built, measured, and rejected by evidence
    rather than by assertion. Do not use it in a published procedure.
    """
    if raw is None:
        return ParsedCount(ParseStatus.MISSING, reason="pack size is absent")
    text = str(raw).strip().lower()
    if not text:
        return ParsedCount(ParseStatus.MISSING, reason="pack size is empty")

    if len(text) > 40:
        return ParsedCount(
            ParseStatus.AMBIGUOUS, reason="count exceeds supported length"
        )
    match = _COUNT_PATTERN.match(text)
    if match is None:
        if lenient:
            loose = re.match(r"^(\d+)", text)
            if loose is not None and int(loose.group(1)) > 0:
                return ParsedCount(ParseStatus.OK, value=int(loose.group(1)))
        return ParsedCount(
            ParseStatus.AMBIGUOUS, reason=f"pack size {text!r} is not a plain count"
        )

    digits, suffix = match.group(1), match.group(2)
    number = int(digits)

    if lenient and number > 0:
        return ParsedCount(ParseStatus.OK, value=number)

    if suffix in DIMENSION_UNITS:
        return ParsedCount(
            ParseStatus.AMBIGUOUS,
            reason=f"pack size {text!r} carries the dimension unit {suffix!r}, not a count",
        )
    if suffix and suffix not in COUNT_NOUNS:
        return ParsedCount(
            ParseStatus.AMBIGUOUS,
            reason=f"pack size {text!r} carries an unrecognized suffix {suffix!r}",
        )
    if number == 0:
        return ParsedCount(
            ParseStatus.AMBIGUOUS, reason="pack size of zero is not usable"
        )
    return ParsedCount(ParseStatus.OK, value=number)
