"""Interpreter behaviour: determinism, branch exclusivity, and safe refusal."""

from __future__ import annotations

import itertools
from decimal import Decimal

from skillfoundry_domain import library
from skillfoundry_domain.ast import (
    All,
    Binding,
    Branch,
    BranchCase,
    Compare,
    ConvertPerUnit,
    Emit,
    Literal,
    ParseCount,
    ParseMoney,
    ReadField,
    Ref,
    RequestReview,
)
from skillfoundry_domain.interpreter import (
    SupplierContext,
    TerminalState,
    matching_cases,
    run,
)
from skillfoundry_domain.procedure import Procedure
from skillfoundry_domain.units import Locale

CTX = SupplierContext("acme", Locale.US, "USD")

PRICE_UNITS = ["carton", "case", "box", "bundle", "item", "each", "unit", "pallet", "", "CARTON"]
PACK_SIZES = ["12", "1", "0", "", "12 mm", "12 pk", "assorted", "3 kg", "24", "12-24"]
PRICES = ["120", "0.90", "", "abc"]


def _rows():
    for unit, pack, price in itertools.product(PRICE_UNITS, PACK_SIZES, PRICES):
        yield {
            "supplier_sku": "T-1",
            "description": "test row",
            "price": price,
            "price_unit": unit,
            "pack_size": pack,
        }


def test_branch_cases_are_mutually_exclusive_for_every_procedure():
    # Reading order must never decide the outcome. If two conditions can hold
    # at once, a later edit to the ordering silently changes behaviour.
    rows = list(_rows())
    for name in library.REGISTRY:
        procedure = library.load(name)
        branch = procedure.body[0]
        assert isinstance(branch, Branch)
        for row in rows:
            hits = matching_cases(branch, row, library.TABLES, CTX)
            assert len(hits) <= 1, (
                f"{name} matched cases {hits} for {row}, so its conditions overlap"
            )


def test_every_row_is_handled_by_some_path():
    for name in library.REGISTRY:
        procedure = library.load(name)
        for row in _rows():
            execution = run(procedure, row, tables=library.TABLES, context=CTX)
            assert execution.terminal_state in {
                TerminalState.COMPLETED,
                TerminalState.NEEDS_REVIEW,
            }, f"{name} faulted on {row}: {execution.fault}"


def test_execution_is_deterministic():
    procedure = library.load("corrected")
    row = {
        "supplier_sku": "AC-100",
        "description": "Hex bolt pack",
        "price": "120",
        "price_unit": "carton",
        "pack_size": "12",
    }
    first = run(procedure, row, tables=library.TABLES, context=CTX)
    for _ in range(50):
        again = run(procedure, row, tables=library.TABLES, context=CTX)
        assert again.output == first.output
        assert [r.code for r in again.reviews] == [r.code for r in first.reviews]
        assert again.procedure_digest == first.procedure_digest


def test_the_taught_case_produces_the_taught_answer():
    procedure = library.load("corrected")
    execution = run(
        procedure,
        {
            "supplier_sku": "AC-100",
            "description": "Hex bolt pack",
            "price": "120",
            "price_unit": "carton",
            "pack_size": "12",
        },
        tables=library.TABLES,
        context=CTX,
    )
    assert execution.terminal_state is TerminalState.COMPLETED
    assert execution.output["unit_price"] == Decimal("10.0000")
    assert execution.output["price_basis"] == "per_unit_from_pack"
    assert execution.output["pack_size"] == 12


def test_the_challenge_case_is_left_alone():
    # "Bolt 12 mm" priced per item. The 12 is a diameter. Dividing would be a
    # silent tenfold error, so the price must pass through untouched.
    procedure = library.load("corrected")
    execution = run(
        procedure,
        {
            "supplier_sku": "BO-200",
            "description": "Bolt 12 mm",
            "price": "10",
            "price_unit": "item",
            "pack_size": "12 mm",
        },
        tables=library.TABLES,
        context=CTX,
    )
    assert execution.output["unit_price"] == Decimal("10")
    assert execution.output["price_basis"] == "as_listed"


def test_a_pack_row_with_an_unusable_pack_size_is_declined_not_guessed():
    procedure = library.load("corrected")
    execution = run(
        procedure,
        {
            "supplier_sku": "BO-207",
            "description": "Pin 6 mm carton",
            "price": "90",
            "price_unit": "carton",
            "pack_size": "6 mm",
        },
        tables=library.TABLES,
        context=CTX,
    )
    assert execution.terminal_state is TerminalState.NEEDS_REVIEW
    assert execution.reviews[0].code == "pack_size_not_explicit"
    assert "unit_price" not in execution.output


def test_an_unrecognized_price_unit_is_declined():
    procedure = library.load("corrected")
    execution = run(
        procedure,
        {
            "supplier_sku": "X-1",
            "description": "Bulk pallet",
            "price": "900",
            "price_unit": "pallet",
            "pack_size": "10",
        },
        tables=library.TABLES,
        context=CTX,
    )
    assert execution.reviews[0].code == "unknown_price_unit"


def test_normalization_is_idempotent():
    # Feeding a normalized per item price back through the procedure must not
    # change it. A rule that divides twice would halve prices on a re-run.
    procedure = library.load("corrected")
    first = run(
        procedure,
        {
            "supplier_sku": "AC-100",
            "description": "Hex bolt pack",
            "price": "120",
            "price_unit": "carton",
            "pack_size": "12",
        },
        tables=library.TABLES,
        context=CTX,
    )
    unit_price = first.output["unit_price"]
    second = run(
        procedure,
        {
            "supplier_sku": "AC-100",
            "description": "Hex bolt pack",
            "price": str(unit_price),
            "price_unit": "item",
            "pack_size": "",
        },
        tables=library.TABLES,
        context=CTX,
    )
    assert second.output["unit_price"] == unit_price


def test_convert_refuses_an_ambiguous_count_and_the_row_is_marked_invalid():
    # An unguarded conversion is a defect. The interpreter must fault rather
    # than divide by a diameter, and it must not leave a partial row behind.
    unguarded = Procedure(
        procedure_id="test.unguarded",
        revision=1,
        name="unguarded conversion",
        input_schema=library.INPUT_SCHEMA,
        output_schema=library.OUTPUT_SCHEMA,
        bindings=(
            Binding(name="money", value=ParseMoney(source=ReadField(field="price"))),
            Binding(name="count", value=ParseCount(source=ReadField(field="pack_size"))),
        ),
        body=(
            Branch(
                cases=[
                    BranchCase(
                        when=Compare(comparison="is_ok", left=Ref(name="money")),
                        body=[
                            Emit(field="sku", value=ReadField(field="supplier_sku")),
                            Emit(
                                field="unit_price",
                                value=ConvertPerUnit(price=Ref(name="money"), count=Ref(name="count")),
                            ),
                        ],
                    )
                ],
                otherwise=[RequestReview(code="unparsed", reason="no price")],
            ),
        ),
    )
    assert unguarded.validate_structure(library.TABLES).ok

    execution = run(
        unguarded,
        {
            "supplier_sku": "T-1",
            "description": "trap",
            "price": "90",
            "price_unit": "carton",
            "pack_size": "6 mm",
        },
        tables=library.TABLES,
        context=CTX,
    )
    assert execution.terminal_state is TerminalState.INVALID
    assert "convert refused" in execution.fault
    assert execution.output == {}


def test_evidence_names_the_source_columns_behind_a_value():
    procedure = library.load("corrected")
    execution = run(
        procedure,
        {
            "supplier_sku": "AC-100",
            "description": "Hex bolt pack",
            "price": "120",
            "price_unit": "carton",
            "pack_size": "12",
        },
        tables=library.TABLES,
        context=CTX,
    )
    evidence = execution.evidence["unit_price"]
    assert set(evidence.source_fields) == {"price", "pack_size"}
    assert evidence.rule_path.startswith("body/")


def test_a_missing_required_input_is_declined_before_any_rule_runs():
    procedure = library.load("corrected")
    execution = run(
        procedure,
        {"supplier_sku": "", "description": "no sku", "price": "10", "price_unit": "item", "pack_size": ""},
        tables=library.TABLES,
        context=CTX,
    )
    assert execution.terminal_state is TerminalState.NEEDS_REVIEW
    assert execution.reviews[0].code == "missing_required_input"


def test_rounding_is_reported_when_the_division_is_inexact():
    procedure = library.load("corrected")
    execution = run(
        procedure,
        {
            "supplier_sku": "AC-108",
            "description": "Clip carton",
            "price": "100",
            "price_unit": "carton",
            "pack_size": "3",
        },
        tables=library.TABLES,
        context=CTX,
    )
    assert execution.output["unit_price"] == Decimal("33.3333")
    assert execution.rounding_applied is True


def test_the_european_feed_needs_its_declared_locale_to_be_read_correctly():
    procedure = library.load("corrected")
    row = {
        "supplier_sku": "CO-300",
        "description": "Bolt carton",
        "price": "1.234,56",
        "price_unit": "carton",
        "pack_size": "12",
    }
    eu = run(procedure, row, tables=library.TABLES, context=SupplierContext("corvid", Locale.EU, "EUR"))
    us = run(procedure, row, tables=library.TABLES, context=SupplierContext("corvid", Locale.US, "EUR"))
    assert eu.output["unit_price"] == Decimal("102.8800")
    # Under the wrong convention the same string parses to a different number,
    # which is why the interpreter never infers it.
    assert us.terminal_state is TerminalState.NEEDS_REVIEW or us.output["unit_price"] != eu.output["unit_price"]
