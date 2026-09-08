"""The two baselines a candidate procedure has to beat.

Baseline one is the original procedure with no corrections applied. It is the
honest starting point.

Baseline two is what happens when a correction is simply remembered rather than
generalized. It reproduces the taught row exactly and falls back to the original
behaviour everywhere else.

Baseline two is a deterministic stand in for pasting the correction into a
prompt as plain text. It is not a language model. It is a lower bound on that
approach, because it always recalls the taught row perfectly and never
misapplies it, which a prompted model would not guarantee. It exists so that a
learned rule has to demonstrate transfer, not memorization. A future milestone
replaces it with a measured model adapter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Protocol

from skillfoundry_domain.interpreter import (
    Evidence,
    Execution,
    SupplierContext,
    run,
)
from skillfoundry_domain.procedure import Procedure


def row_digest(values: Mapping[str, str]) -> str:
    payload = json.dumps(
        {k: ("" if v is None else str(v)) for k, v in sorted(values.items())},
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Evaluable(Protocol):
    name: str
    label: str

    def execute(
        self,
        values: Mapping[str, str],
        context: SupplierContext,
        row_id: str,
    ) -> Execution: ...


@dataclass
class ProcedureRunner:
    """Runs a validated procedure through the trusted interpreter."""

    procedure: Procedure
    tables: Mapping[str, Mapping[str, str]]
    name: str
    label: str

    def execute(
        self, values: Mapping[str, str], context: SupplierContext, row_id: str
    ) -> Execution:
        return run(
            self.procedure,
            values,
            tables=self.tables,
            context=context,
            row_id=row_id,
        )


@dataclass
class LiteralRecall:
    """Baseline two. Recalls taught rows verbatim, otherwise falls back."""

    fallback: ProcedureRunner
    corrections: dict[str, dict[str, object]]
    name: str = "baseline_literal_recall"
    label: str = "Baseline 2, verbatim recall"

    def execute(
        self, values: Mapping[str, str], context: SupplierContext, row_id: str
    ) -> Execution:
        digest = row_digest(values)
        if digest not in self.corrections:
            return self.fallback.execute(values, context, row_id)

        corrected = self.corrections[digest]
        execution = Execution(
            procedure_id=self.fallback.procedure.procedure_id,
            procedure_revision=self.fallback.procedure.revision,
            procedure_digest=f"recall:{self.fallback.procedure.digest}",
            row_id=row_id,
        )
        execution.output["sku"] = values.get("supplier_sku")
        execution.output["name"] = values.get("description")
        execution.output["unit_price"] = Decimal(str(corrected["unit_price"]))
        execution.output["price_basis"] = corrected["price_basis"]
        if corrected.get("pack_size") is not None:
            execution.output["pack_size"] = corrected["pack_size"]
        for field_name in execution.output:
            execution.evidence[field_name] = Evidence(
                rule_path="recall/taught_row",
                source_fields=tuple(sorted(values)),
                note="value recalled from a taught correction for this exact row",
            )
        return execution


def load_corrections(
    path: Path, rows_by_case: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, object]]:
    """Index taught corrections by the digest of the row they were taught on."""
    corrections: dict[str, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        values = rows_by_case.get(payload["case_id"])
        if values is None:
            raise KeyError(f"teaching case {payload['case_id']!r} has no source row")
        corrections[row_digest(values)] = payload["corrected"]
    return corrections
