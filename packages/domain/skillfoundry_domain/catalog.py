"""Loading supplier feeds and their declared decimal conventions."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .interpreter import SupplierContext
from .units import Locale


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    locale: Locale
    currency: str
    split: str
    note: str = ""

    @property
    def context(self) -> SupplierContext:
        return SupplierContext(self.supplier_id, self.locale, self.currency)


@dataclass(frozen=True)
class SourceRow:
    supplier_id: str
    row_id: str
    values: dict[str, str]


def load_suppliers(root: Path) -> dict[str, Supplier]:
    payload = json.loads((root / "suppliers.json").read_text(encoding="utf-8"))
    out: dict[str, Supplier] = {}
    for supplier_id, spec in payload.items():
        out[supplier_id] = Supplier(
            supplier_id=supplier_id,
            locale=Locale(spec["locale"]),
            currency=spec["currency"],
            split=spec["split"],
            note=spec.get("note", ""),
        )
    return out


def load_rows(root: Path, supplier_id: str) -> Iterator[SourceRow]:
    path = root / "suppliers" / f"{supplier_id}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            values = {k: (v if v is not None else "") for k, v in record.items()}
            yield SourceRow(supplier_id, values["supplier_sku"], values)


def load_all_rows(root: Path, suppliers: dict[str, Supplier]) -> dict[str, SourceRow]:
    index: dict[str, SourceRow] = {}
    for supplier_id in suppliers:
        for row in load_rows(root, supplier_id):
            index[f"{supplier_id}:{row.row_id}"] = row
    return index
