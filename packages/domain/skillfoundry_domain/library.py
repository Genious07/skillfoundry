"""The demonstration procedure library.

Three procedures tell the whole product story.

`naive` is what a first draft produces: it copies the listed price into the
unit price and never asks about pack units. It is correct on per item feeds and
wrong by the pack factor on carton feeds.

`corrected` is the candidate a specialist teaches after seeing one carton row
go wrong. The correction reveals a missing condition, so the rule divides only
when the price is quoted per pack and the pack size is an explicit count, and
asks for review otherwise.

`overeager` is the candidate that looks like the correction but generalizes too
far: it divides whenever the pack size column starts with a number, ignoring
both the price unit and whether that number is a count. It exists so the
evaluation harness has a genuinely plausible wrong answer to reject.
"""

from __future__ import annotations

from .ast import (
    All,
    Any_,
    Binding,
    Branch,
    BranchCase,
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
)
from .procedure import FieldSpec, Procedure

# Supplier tokens mapped onto a controlled vocabulary. "pack" means the price
# covers several items, "single" means it covers one.
UNIT_KIND_TABLE: dict[str, str] = {
    "carton": "pack",
    "ctn": "pack",
    "case": "pack",
    "box": "pack",
    "pack": "pack",
    "bundle": "pack",
    "item": "single",
    "each": "single",
    "ea": "single",
    "unit": "single",
    "piece": "single",
}

TABLES: dict[str, dict[str, str]] = {"unit_kind": UNIT_KIND_TABLE}

INPUT_SCHEMA = (
    FieldSpec(name="supplier_sku", kind="text", required=True),
    FieldSpec(name="description", kind="text", required=True),
    FieldSpec(name="price", kind="money", required=True),
    FieldSpec(name="price_unit", kind="text"),
    FieldSpec(name="pack_size", kind="text"),
)

OUTPUT_SCHEMA = (
    FieldSpec(name="sku", kind="text"),
    FieldSpec(name="name", kind="text"),
    FieldSpec(name="unit_price", kind="money"),
    FieldSpec(name="pack_size", kind="count"),
    FieldSpec(name="price_basis", kind="text"),
)

_IDENTITY_EMITS = [
    Emit(field="sku", value=ReadField(field="supplier_sku")),
    Emit(field="name", value=ReadField(field="description")),
]


def naive() -> Procedure:
    """Revision 1. Copies the listed price into the unit price."""
    return Procedure(
        procedure_id="catalog.unit_price",
        revision=1,
        name="Unit price, first draft",
        description="Emit the listed price as the unit price. No pack handling.",
        origin="authored",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        required_tables=(),
        bindings=(Binding(name="money", value=ParseMoney(source=ReadField(field="price"))),),
        body=(
            Branch(
                cases=[
                    BranchCase(
                        when=Compare(comparison="is_ok", left=Ref(name="money")),
                        body=[
                            *_IDENTITY_EMITS,
                            Emit(field="unit_price", value=Ref(name="money")),
                            Emit(field="price_basis", value=Literal(value="as_listed")),
                        ],
                    )
                ],
                otherwise=[
                    RequestReview(
                        code="unparsed_price",
                        reason="The price could not be read as a number.",
                    )
                ],
            ),
        ),
    )


def corrected() -> Procedure:
    """Revision 2. Divides pack prices only when the pack size is a real count."""
    return Procedure(
        procedure_id="catalog.unit_price",
        revision=2,
        parent_revision=1,
        name="Unit price with explicit pack normalization",
        description=(
            "When the price is quoted per pack and the pack size is an explicit "
            "count, divide to get a per item price. When the price is per pack "
            "but the pack size is not an explicit count, ask for review rather "
            "than guessing."
        ),
        origin="authored",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        required_tables=("unit_kind",),
        bindings=(
            Binding(name="money", value=ParseMoney(source=ReadField(field="price"))),
            Binding(name="count", value=ParseCount(source=ReadField(field="pack_size"))),
            Binding(
                name="basis",
                value=Lookup(
                    table="unit_kind",
                    key=ReadField(field="price_unit"),
                    default="unknown",
                ),
            ),
        ),
        body=(
            Branch(
                cases=[
                    # Conditions are written to be mutually exclusive so that
                    # reading order never changes the outcome. The exclusivity
                    # property test enforces this.
                    BranchCase(
                        when=Not(term=Compare(comparison="is_ok", left=Ref(name="money"))),
                        body=[
                            RequestReview(
                                code="unparsed_price",
                                reason="The price could not be read as a number.",
                            )
                        ],
                    ),
                    BranchCase(
                        when=All(
                            terms=[
                                Compare(comparison="is_ok", left=Ref(name="money")),
                                Compare(
                                    comparison="eq",
                                    left=Ref(name="basis"),
                                    right=Literal(value="unknown"),
                                ),
                            ]
                        ),
                        body=[
                            RequestReview(
                                code="unknown_price_unit",
                                reason=(
                                    "The price unit is not a recognized pack or single "
                                    "item term, so the basis of the price is unclear."
                                ),
                            )
                        ],
                    ),
                    BranchCase(
                        when=All(
                            terms=[
                                Compare(comparison="is_ok", left=Ref(name="money")),
                                Compare(
                                    comparison="eq",
                                    left=Ref(name="basis"),
                                    right=Literal(value="pack"),
                                ),
                                Compare(comparison="is_ok", left=Ref(name="count")),
                            ]
                        ),
                        body=[
                            *_IDENTITY_EMITS,
                            Emit(
                                field="unit_price",
                                value=ConvertPerUnit(
                                    price=Ref(name="money"), count=Ref(name="count")
                                ),
                            ),
                            Emit(field="pack_size", value=Ref(name="count")),
                            Emit(
                                field="price_basis",
                                value=Literal(value="per_unit_from_pack"),
                            ),
                        ],
                    ),
                    BranchCase(
                        when=All(
                            terms=[
                                Compare(comparison="is_ok", left=Ref(name="money")),
                                Compare(
                                    comparison="eq",
                                    left=Ref(name="basis"),
                                    right=Literal(value="pack"),
                                ),
                                Not(term=Compare(comparison="is_ok", left=Ref(name="count"))),
                            ]
                        ),
                        body=[
                            RequestReview(
                                code="pack_size_not_explicit",
                                reason=(
                                    "This row is priced per pack but the pack size is "
                                    "not an explicit count, so the number of items is "
                                    "unknown. Provide the pack size to convert it."
                                ),
                            )
                        ],
                    ),
                    BranchCase(
                        when=All(
                            terms=[
                                Compare(comparison="is_ok", left=Ref(name="money")),
                                Compare(
                                    comparison="eq",
                                    left=Ref(name="basis"),
                                    right=Literal(value="single"),
                                ),
                            ]
                        ),
                        body=[
                            *_IDENTITY_EMITS,
                            Emit(field="unit_price", value=Ref(name="money")),
                            Emit(field="price_basis", value=Literal(value="as_listed")),
                        ],
                    ),
                ],
                otherwise=[
                    RequestReview(
                        code="unhandled_row",
                        reason="No rule covered this row.",
                    )
                ],
            ),
        ),
    )


def overeager() -> Procedure:
    """Revision 2, rejected. Divides on any leading number in the pack column."""
    return Procedure(
        procedure_id="catalog.unit_price",
        revision=2,
        parent_revision=1,
        name="Unit price, over generalized",
        description=(
            "Divides the price by whatever number appears in the pack size "
            "column, ignoring the price unit and ignoring whether the number is "
            "a count. Retained as a rejected candidate."
        ),
        origin="proposed",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        required_tables=(),
        bindings=(
            Binding(name="money", value=ParseMoney(source=ReadField(field="price"))),
            Binding(
                name="count",
                value=ParseCount(source=ReadField(field="pack_size"), lenient=True),
            ),
        ),
        body=(
            Branch(
                cases=[
                    BranchCase(
                        when=Not(term=Compare(comparison="is_ok", left=Ref(name="money"))),
                        body=[
                            RequestReview(
                                code="unparsed_price",
                                reason="The price could not be read as a number.",
                            )
                        ],
                    ),
                    BranchCase(
                        when=All(
                            terms=[
                                Compare(comparison="is_ok", left=Ref(name="money")),
                                Compare(comparison="is_ok", left=Ref(name="count")),
                            ]
                        ),
                        body=[
                            *_IDENTITY_EMITS,
                            Emit(
                                field="unit_price",
                                value=ConvertPerUnit(
                                    price=Ref(name="money"), count=Ref(name="count")
                                ),
                            ),
                            Emit(field="pack_size", value=Ref(name="count")),
                            Emit(
                                field="price_basis",
                                value=Literal(value="per_unit_from_pack"),
                            ),
                        ],
                    ),
                    BranchCase(
                        when=All(
                            terms=[
                                Compare(comparison="is_ok", left=Ref(name="money")),
                                Not(term=Compare(comparison="is_ok", left=Ref(name="count"))),
                            ]
                        ),
                        body=[
                            *_IDENTITY_EMITS,
                            Emit(field="unit_price", value=Ref(name="money")),
                            Emit(field="price_basis", value=Literal(value="as_listed")),
                        ],
                    ),
                ],
                otherwise=[
                    RequestReview(code="unhandled_row", reason="No rule covered this row.")
                ],
            ),
        ),
    )


REGISTRY = {"naive": naive, "corrected": corrected, "overeager": overeager}


def load(name: str) -> Procedure:
    if name not in REGISTRY:
        raise KeyError(f"unknown procedure {name!r}, expected one of {sorted(REGISTRY)}")
    return REGISTRY[name]()
