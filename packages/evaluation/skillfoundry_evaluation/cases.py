"""Evaluation cases and their provenance.

A case records what a reviewer decided the correct outcome is. Real cases come
from a supplier feed. Generated cases are counterexamples written to probe a
rule boundary. The two never merge, because a rule that only satisfies its own
generated counterexamples has not been shown to transfer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class ExpectedValue:
    unit_price: Decimal
    price_basis: str
    pack_size: int | None = None
    kind: Literal["value"] = "value"


@dataclass(frozen=True)
class ExpectedReview:
    code: str
    kind: Literal["review"] = "review"


Expectation = ExpectedValue | ExpectedReview


@dataclass(frozen=True)
class Case:
    case_id: str
    supplier: str
    origin: Literal["real", "generated"]
    split: str
    expect: Expectation
    row: dict[str, str] | None = None
    rationale: str = ""
    label_reviewed: bool = True


def _parse_expectation(payload: dict[str, Any]) -> Expectation:
    if payload["kind"] == "value":
        return ExpectedValue(
            unit_price=Decimal(payload["unit_price"]),
            price_basis=payload["price_basis"],
            pack_size=payload.get("pack_size"),
        )
    if payload["kind"] == "review":
        return ExpectedReview(code=payload["code"])
    raise ValueError(f"unknown expectation kind {payload['kind']!r}")


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        cases.append(
            Case(
                case_id=payload["case_id"],
                supplier=payload["supplier"],
                origin=payload["origin"],
                split=payload["split"],
                expect=_parse_expectation(payload["expect"]),
                row=payload.get("row"),
                rationale=payload.get("rationale", ""),
                label_reviewed=payload.get("label_reviewed", True),
            )
        )
    return cases


def load_case_sets(root: Path) -> dict[str, list[Case]]:
    """Load the fixture case sets, keeping origins separate by construction."""
    return {
        "real": load_cases(root / "cases" / "real.jsonl"),
        "generated": load_cases(root / "cases" / "generated.jsonl"),
    }
