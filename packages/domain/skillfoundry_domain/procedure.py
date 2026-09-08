"""Procedure versions, capability declarations, validation, and digests.

A procedure carries everything a reviewer needs to judge whether it is safe to
publish: the fields it reads, the fields it writes, the operators it is allowed
to use, and an immutable digest of its structure. Validation happens before
execution, so a malformed or over-privileged proposal never reaches the
interpreter.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from .ast import (
    OPERATOR_NAMES,
    Binding,
    Branch,
    Emit,
    Expr,
    Lookup,
    ReadField,
    Ref,
    RequestReview,
    Stmt,
    operator_of,
    walk,
)


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    detail: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def describe(self) -> str:
        if self.ok:
            return "valid"
        return "; ".join(f"{i.code}: {i.detail}" for i in self.issues)


class FieldSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    kind: str  # text, money, count, bool
    required: bool = False


class Procedure(BaseModel):
    """An immutable, validated catalog normalization procedure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    procedure_id: str
    revision: int
    name: str
    description: str = ""
    parent_revision: int | None = None
    origin: str = "authored"  # authored, proposed, derived

    input_schema: tuple[FieldSpec, ...]
    output_schema: tuple[FieldSpec, ...]
    allowed_operators: frozenset[str] = Field(default_factory=lambda: frozenset(OPERATOR_NAMES))
    required_tables: tuple[str, ...] = ()
    # Side effect permissions. The first release is read only by construction:
    # a procedure produces an output row and review requests, nothing else.
    capabilities: tuple[str, ...] = ("read_only",)

    bindings: tuple[Binding, ...] = ()
    body: tuple[Stmt, ...] = Field(min_length=1)

    def canonical_json(self) -> str:
        payload = self.model_dump(mode="json")
        # allowed_operators is a set, so sort it for a stable digest.
        payload["allowed_operators"] = sorted(payload["allowed_operators"])
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()[:16]

    @property
    def input_fields(self) -> frozenset[str]:
        return frozenset(f.name for f in self.input_schema)

    @property
    def output_fields(self) -> frozenset[str]:
        return frozenset(f.name for f in self.output_schema)

    def operators_used(self) -> frozenset[str]:
        return frozenset(operator_of(node) for node in walk(list(self.body)) ) | frozenset(
            operator_of(node) for node in walk([b.value for b in self.bindings])
        )

    def validate_structure(self, tables: Mapping[str, Mapping[str, str]] | None = None) -> ValidationReport:
        issues: list[ValidationIssue] = []
        tables = tables or {}

        used = self.operators_used()
        for name in sorted(used - self.allowed_operators):
            issues.append(
                ValidationIssue(
                    code="operator_not_permitted",
                    detail=f"procedure uses {name!r} which is not in its allowed operator set",
                )
            )
        for name in sorted(self.allowed_operators - OPERATOR_NAMES):
            issues.append(
                ValidationIssue(
                    code="unknown_operator",
                    detail=f"{name!r} is not a known operator",
                )
            )

        # Bindings must be defined before they are referenced.
        defined: set[str] = set()
        for binding in self.bindings:
            for node in walk(binding.value):
                if isinstance(node, Ref) and node.name not in defined:
                    issues.append(
                        ValidationIssue(
                            code="unresolved_reference",
                            detail=f"binding {binding.name!r} references {node.name!r} before it is defined",
                        )
                    )
            if binding.name in defined:
                issues.append(
                    ValidationIssue(
                        code="duplicate_binding",
                        detail=f"binding {binding.name!r} is defined more than once",
                    )
                )
            defined.add(binding.name)

        all_nodes = list(walk(list(self.body)))
        for node in all_nodes:
            if isinstance(node, Ref) and node.name not in defined:
                issues.append(
                    ValidationIssue(
                        code="unresolved_reference",
                        detail=f"body references undefined binding {node.name!r}",
                    )
                )

        every_node = all_nodes + list(walk([b.value for b in self.bindings]))
        for node in every_node:
            if isinstance(node, ReadField) and node.field not in self.input_fields:
                issues.append(
                    ValidationIssue(
                        code="undeclared_input",
                        detail=f"reads {node.field!r} which is not in the input schema",
                    )
                )
            if isinstance(node, Emit) and node.field not in self.output_fields:
                issues.append(
                    ValidationIssue(
                        code="undeclared_output",
                        detail=f"emits {node.field!r} which is not in the output schema",
                    )
                )
            if isinstance(node, Lookup):
                if node.table not in self.required_tables:
                    issues.append(
                        ValidationIssue(
                            code="undeclared_table",
                            detail=f"uses lookup table {node.table!r} which the procedure does not declare",
                        )
                    )
                elif node.table not in tables:
                    issues.append(
                        ValidationIssue(
                            code="missing_table",
                            detail=f"declared lookup table {node.table!r} was not supplied",
                        )
                    )

        # A procedure that can never ask for help is a procedure that will
        # guess on an ambiguous row.
        if not any(isinstance(node, RequestReview) for node in all_nodes):
            issues.append(
                ValidationIssue(
                    code="no_abstention_path",
                    detail="procedure has no request_review path, so it cannot decline an ambiguous case",
                )
            )

        for cap in self.capabilities:
            if cap != "read_only":
                issues.append(
                    ValidationIssue(
                        code="capability_not_supported",
                        detail=f"capability {cap!r} is not supported in this release",
                    )
                )

        return ValidationReport(issues=tuple(issues))
