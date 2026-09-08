"""Typed abstract syntax tree for a catalog procedure.

A procedure is data, not code. A model may propose combinations of these nodes
and nothing else. There is no eval, no exec, and no path by which a proposal
becomes arbitrary Python. Every node below is implemented by trusted code in
interpreter.py with declared input and output types.

The operator vocabulary is fixed at eight names, matching the product contract:
read_field, parse_unit, lookup, compare, branch, convert, emit, request_review.
parse_unit has two typed variants because parsing money and parsing a count
have different failure modes and must not share an implementation.
"""

from __future__ import annotations

from typing import Annotated, Literal as TypingLiteral, Union

from pydantic import BaseModel, ConfigDict, Field

from .units import Locale


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# Operator names used for capability checks. A procedure declares which of
# these it is allowed to use and validation rejects anything outside that set.
OPERATOR_NAMES: frozenset[str] = frozenset(
    {
        "read_field",
        "parse_unit",
        "lookup",
        "compare",
        "branch",
        "convert",
        "emit",
        "request_review",
    }
)


# Expressions ---------------------------------------------------------------


class Literal(Node):
    op: TypingLiteral["literal"] = "literal"
    value: str | int | bool | None = None

    operator_name: TypingLiteral["read_field"] = "read_field"


class Ref(Node):
    """Reference to a named binding. A variable reference, not an operator."""

    op: TypingLiteral["ref"] = "ref"
    name: str


class ReadField(Node):
    op: TypingLiteral["read_field"] = "read_field"
    field: str


class ParseMoney(Node):
    op: TypingLiteral["parse_money"] = "parse_money"
    source: "Expr"
    currency: str | None = None
    # None means take the decimal convention from the supplier context. A
    # procedure that hardcodes a locale is only valid for feeds using it.
    locale: Locale | None = None


class ParseCount(Node):
    op: TypingLiteral["parse_count"] = "parse_count"
    source: "Expr"
    # Lenient parsing accepts a leading integer whatever unit follows it. It
    # exists so an unsafe proposal can be measured and rejected on evidence.
    lenient: bool = False


class Lookup(Node):
    """Map a raw supplier token onto a controlled vocabulary term."""

    op: TypingLiteral["lookup"] = "lookup"
    table: str
    key: "Expr"
    default: str | None = None
    normalize: bool = True


class Compare(Node):
    op: TypingLiteral["compare"] = "compare"
    comparison: TypingLiteral[
        "eq", "ne", "in", "not_in", "is_ok", "is_missing", "is_ambiguous", "is_blank"
    ]
    left: "Expr"
    right: "Expr | None" = None


class All(Node):
    op: TypingLiteral["all"] = "all"
    terms: list["Expr"] = Field(min_length=1)


class Any_(Node):
    op: TypingLiteral["any"] = "any"
    terms: list["Expr"] = Field(min_length=1)


class Not(Node):
    op: TypingLiteral["not"] = "not"
    term: "Expr"


class ConvertPerUnit(Node):
    """Divide a pack price by an explicit count to get a unit price.

    Both operands must be successful parse outcomes. The interpreter refuses to
    convert an ambiguous count, which is the guard that stops a dimension from
    being read as a pack size.
    """

    op: TypingLiteral["convert_per_unit"] = "convert_per_unit"
    price: "Expr"
    count: "Expr"


Expr = Annotated[
    Union[
        Literal, Ref, ReadField, ParseMoney, ParseCount, Lookup,
        Compare, All, Any_, Not, ConvertPerUnit,
    ],
    Field(discriminator="op"),
]


# Statements ----------------------------------------------------------------


class Emit(Node):
    op: TypingLiteral["emit"] = "emit"
    field: str
    value: "Expr"


class RequestReview(Node):
    op: TypingLiteral["request_review"] = "request_review"
    code: str
    reason: str


class BranchCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    when: "Expr"
    body: list["Stmt"] = Field(min_length=1)


class Branch(Node):
    op: TypingLiteral["branch"] = "branch"
    cases: list[BranchCase] = Field(min_length=1)
    otherwise: list["Stmt"] = Field(default_factory=list)


Stmt = Annotated[Union[Emit, RequestReview, Branch], Field(discriminator="op")]


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    value: "Expr"


# Mapping from concrete node tag to the declared operator vocabulary.
_NODE_TO_OPERATOR: dict[str, str] = {
    "literal": "read_field",
    "ref": "read_field",
    "read_field": "read_field",
    "parse_money": "parse_unit",
    "parse_count": "parse_unit",
    "lookup": "lookup",
    "compare": "compare",
    "all": "compare",
    "any": "compare",
    "not": "compare",
    "convert_per_unit": "convert",
    "emit": "emit",
    "request_review": "request_review",
    "branch": "branch",
}


def operator_of(node: BaseModel) -> str:
    tag = getattr(node, "op", None)
    if tag is None or tag not in _NODE_TO_OPERATOR:
        raise ValueError(f"node has no known operator tag: {node!r}")
    return _NODE_TO_OPERATOR[tag]


def walk(node: object):
    """Yield every AST node reachable from this node, including itself."""
    if isinstance(node, BaseModel):
        if getattr(node, "op", None) is not None:
            yield node
        for name in type(node).model_fields:
            yield from walk(getattr(node, name))
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


for _model in (
    Literal, Ref, ReadField, ParseMoney, ParseCount, Lookup, Compare,
    All, Any_, Not, ConvertPerUnit, Emit, RequestReview, Branch, BranchCase, Binding,
):
    _model.model_rebuild()
