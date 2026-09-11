"""Deterministic interpreter for catalog procedures.

Given the same procedure, row, tables, and supplier context, this produces the
same output every time. There is no model call, no clock, and no randomness in
the execution path.

Two design points matter for trust.

Convert refuses to operate on an ambiguous parse. A procedure must guard the
conversion with a branch that checks the parse succeeded. If it does not, the
execution terminates as invalid rather than producing a plausible wrong price.

Every emitted field records which source cells and which rule produced it, so
the interface can show evidence for a value instead of asserting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal, DecimalException
from typing import Any, Mapping, Sequence

from .ast import (
    All,
    Any_,
    Binding,
    Branch,
    Compare,
    ConvertPerUnit,
    Emit,
    Literal,
    Lookup,
    Not,
    ParseCount,
    ParseMoney,
    ReadField,
    Ref,
    RequestReview,
    Stmt,
)
from .procedure import Procedure
from .units import (
    Locale,
    Money,
    ParsedCount,
    ParsedMoney,
    ParseStatus,
    parse_count,
    parse_money,
)


class TerminalState(str, Enum):
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    INVALID = "invalid"


class InterpreterError(Exception):
    """A typed execution fault, for example converting an ambiguous count."""


@dataclass(frozen=True)
class SupplierContext:
    supplier_id: str
    locale: Locale
    currency: str


@dataclass(frozen=True)
class Evidence:
    """Why a value looks the way it does."""

    rule_path: str
    source_fields: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class ReviewRequest:
    code: str
    reason: str
    rule_path: str


@dataclass
class Execution:
    procedure_id: str
    procedure_revision: int
    procedure_digest: str
    row_id: str
    output: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    reviews: list[ReviewRequest] = field(default_factory=list)
    fault: str | None = None
    rounding_applied: bool = False

    @property
    def terminal_state(self) -> TerminalState:
        if self.fault is not None:
            return TerminalState.INVALID
        if self.reviews:
            return TerminalState.NEEDS_REVIEW
        return TerminalState.COMPLETED


class _Env:
    def __init__(
        self,
        row: Mapping[str, Any],
        tables: Mapping[str, Mapping[str, str]],
        context: SupplierContext,
    ) -> None:
        self.row = row
        self.tables = tables
        self.context = context
        self.values: dict[str, Any] = {}
        self.sources: dict[str, tuple[str, ...]] = {}


def _sources_of(node: Any, env: _Env) -> tuple[str, ...]:
    """Collect the source column names an expression depends on."""
    from .ast import walk

    names: list[str] = []
    for inner in walk(node):
        if isinstance(inner, ReadField):
            names.append(inner.field)
        elif isinstance(inner, Ref):
            names.extend(env.sources.get(inner.name, ()))
    seen: dict[str, None] = {}
    for n in names:
        seen[n] = None
    return tuple(seen)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise InterpreterError(
        f"condition did not evaluate to a boolean, got {type(value).__name__}"
    )


def _eval(node: Any, env: _Env, path: str) -> Any:
    if isinstance(node, Literal):
        return node.value

    if isinstance(node, Ref):
        if node.name not in env.values:
            raise InterpreterError(f"reference to undefined binding {node.name!r}")
        return env.values[node.name]

    if isinstance(node, ReadField):
        return env.row.get(node.field)

    if isinstance(node, ParseMoney):
        raw = _eval(node.source, env, path)
        currency = node.currency or env.context.currency
        locale = node.locale or env.context.locale
        return parse_money(raw, currency, locale)

    if isinstance(node, ParseCount):
        raw = _eval(node.source, env, path)
        return parse_count(raw, lenient=node.lenient)

    if isinstance(node, Lookup):
        table = env.tables.get(node.table)
        if table is None:
            raise InterpreterError(f"lookup table {node.table!r} is not available")
        raw = _eval(node.key, env, path)
        key = "" if raw is None else str(raw)
        if node.normalize:
            key = key.strip().lower()
        return table.get(key, node.default)

    if isinstance(node, Compare):
        left = _eval(node.left, env, path)
        cmp = node.comparison

        if cmp in {"is_ok", "is_missing", "is_ambiguous"}:
            if not isinstance(left, (ParsedMoney, ParsedCount)):
                raise InterpreterError(
                    f"{cmp} expects a parse outcome, got {type(left).__name__}"
                )
            wanted = {
                "is_ok": ParseStatus.OK,
                "is_missing": ParseStatus.MISSING,
                "is_ambiguous": ParseStatus.AMBIGUOUS,
            }[cmp]
            return left.status is wanted

        if cmp == "is_blank":
            return left is None or str(left).strip() == ""

        if node.right is None:
            raise InterpreterError(f"comparison {cmp!r} requires a right operand")
        right = _eval(node.right, env, path)

        if cmp == "eq":
            return left == right
        if cmp == "ne":
            return left != right
        if cmp in {"in", "not_in"}:
            if not isinstance(right, str):
                raise InterpreterError(
                    "membership test expects a comma separated literal"
                )
            members = {part.strip() for part in right.split(",") if part.strip()}
            present = ("" if left is None else str(left).strip().lower()) in members
            return present if cmp == "in" else not present
        raise InterpreterError(f"unknown comparison {cmp!r}")

    if isinstance(node, All):
        return all(_truthy(_eval(term, env, path)) for term in node.terms)
    if isinstance(node, Any_):
        return any(_truthy(_eval(term, env, path)) for term in node.terms)
    if isinstance(node, Not):
        return not _truthy(_eval(node.term, env, path))

    if isinstance(node, ConvertPerUnit):
        price = _eval(node.price, env, path)
        count = _eval(node.count, env, path)
        if not isinstance(price, ParsedMoney):
            raise InterpreterError(
                f"convert expects parsed money, got {type(price).__name__}"
            )
        if not isinstance(count, ParsedCount):
            raise InterpreterError(
                f"convert expects a parsed count, got {type(count).__name__}"
            )
        if price.status is not ParseStatus.OK or price.value is None:
            raise InterpreterError(
                f"convert refused: price is {price.status.value} ({price.reason})"
            )
        if count.status is not ParseStatus.OK or count.value is None:
            raise InterpreterError(
                f"convert refused: count is {count.status.value} ({count.reason})"
            )
        return price.value.per_unit(count.value)

    raise InterpreterError(f"unsupported expression node {type(node).__name__}")


def _unwrap(value: Any, execution: Execution) -> Any:
    """Turn an internal value into something writable to the output row."""
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], Money):
        money, rounded = value
        if rounded:
            execution.rounding_applied = True
        return money.amount
    if isinstance(value, Money):
        return value.amount
    if isinstance(value, ParsedMoney):
        if value.status is not ParseStatus.OK or value.value is None:
            raise InterpreterError(f"cannot emit an unparsed price: {value.reason}")
        return value.value.amount
    if isinstance(value, ParsedCount):
        if value.status is not ParseStatus.OK or value.value is None:
            raise InterpreterError(f"cannot emit an unparsed count: {value.reason}")
        return value.value
    return value


def _exec(
    statements: Sequence[Stmt], env: _Env, execution: Execution, path: str
) -> None:
    for index, stmt in enumerate(statements):
        here = f"{path}/{index}:{stmt.op}"

        if isinstance(stmt, Emit):
            value = _eval(stmt.value, env, here)
            execution.output[stmt.field] = _unwrap(value, execution)
            execution.evidence[stmt.field] = Evidence(
                rule_path=here,
                source_fields=_sources_of(stmt.value, env),
            )
            continue

        if isinstance(stmt, RequestReview):
            execution.reviews.append(
                ReviewRequest(code=stmt.code, reason=stmt.reason, rule_path=here)
            )
            continue

        if isinstance(stmt, Branch):
            taken = False
            for case_index, case in enumerate(stmt.cases):
                if _truthy(_eval(case.when, env, here)):
                    _exec(case.body, env, execution, f"{here}/case{case_index}")
                    taken = True
                    break
            if not taken and stmt.otherwise:
                _exec(stmt.otherwise, env, execution, f"{here}/otherwise")
            continue

        raise InterpreterError(f"unsupported statement node {type(stmt).__name__}")


def matching_cases(
    branch: Branch, row: Mapping[str, Any], tables, context
) -> list[int]:
    """Indices of every branch case whose condition holds for this row.

    Used by the branch exclusivity property test. A well formed branch matches
    at most one case, so overlapping conditions are a defect the tests catch
    rather than an ordering detail the reader has to reason about.
    """
    env = _Env(row, tables, context)
    hits: list[int] = []
    for index, case in enumerate(branch.cases):
        try:
            if _truthy(_eval(case.when, env, "probe")):
                hits.append(index)
        except InterpreterError:
            continue
    return hits


def run(
    procedure: Procedure,
    row: Mapping[str, Any],
    *,
    tables: Mapping[str, Mapping[str, str]] | None = None,
    context: SupplierContext,
    row_id: str | None = None,
) -> Execution:
    """Execute a procedure against one source row."""
    execution = Execution(
        procedure_id=procedure.procedure_id,
        procedure_revision=procedure.revision,
        procedure_digest=procedure.digest,
        row_id=row_id or str(row.get("supplier_sku", "unknown")),
    )
    validation = procedure.validate_structure(tables)
    if not validation.ok:
        execution.fault = validation.describe()
        return execution
    env = _Env(row, tables or {}, context)

    try:
        for binding in procedure.bindings:
            env.values[binding.name] = _eval(binding.value, env, f"bind:{binding.name}")
            env.sources[binding.name] = _sources_of(binding.value, env)

        for spec in procedure.input_schema:
            if spec.required:
                raw = row.get(spec.name)
                if raw is None or str(raw).strip() == "":
                    execution.reviews.append(
                        ReviewRequest(
                            code="missing_required_input",
                            reason=f"required field {spec.name!r} is absent",
                            rule_path="precondition",
                        )
                    )
        if execution.reviews:
            return execution

        _exec(list(procedure.body), env, execution, "body")
        if execution.reviews:
            execution.output.clear()
            execution.evidence.clear()
        else:
            for spec in procedure.output_schema:
                value = execution.output.get(spec.name)
                if value is None and not spec.required:
                    continue
                valid = {
                    "money": lambda v: (
                        isinstance(v, Decimal) and v.is_finite() and v >= 0
                    ),
                    "count": lambda v: type(v) is int and v > 0,
                    "text": lambda v: isinstance(v, str),
                    "bool": lambda v: type(v) is bool,
                }
                if spec.kind not in valid or not valid[spec.kind](value):
                    raise InterpreterError(f"output {spec.name!r} must be {spec.kind}")
    except (InterpreterError, DecimalException, ValueError) as exc:
        execution.fault = str(exc)
        execution.output.clear()
        execution.evidence.clear()
        execution.rounding_applied = False

    return execution
