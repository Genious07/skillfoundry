"""Independent edge cases found while auditing the original fixture claims."""

from decimal import Decimal, localcontext

import pytest
from skillfoundry_domain import library
from skillfoundry_domain.ast import Emit, Literal
from skillfoundry_domain.interpreter import (
    Execution,
    SupplierContext,
    TerminalState,
    run,
)
from skillfoundry_domain.units import Locale, Money, ParseStatus, parse_money
from skillfoundry_evaluation.baselines import LiteralRecall, ProcedureRunner, recall_key
from skillfoundry_evaluation.cases import Case, ExpectedValue
from skillfoundry_evaluation.metrics import (
    CaseOutcome,
    Verdict,
    compare_paired,
    grade,
    summarize,
)


@pytest.mark.parametrize(
    "raw",
    [
        "1e3",
        "10/12",
        "(10)",
        "USD 10 each",
        "1,23",
        "12abc34",
        "€10",
        "--10",
        "NaN",
        "Infinity",
    ],
)
def test_money_refuses_malformed_tokens(raw):
    assert parse_money(raw, "USD", Locale.US).status is ParseStatus.AMBIGUOUS


def test_money_division_does_not_inherit_callers_precision():
    with localcontext() as ctx:
        ctx.prec = 3
        value, rounded = Money(Decimal("99.99"), "USD").per_unit(20)
    assert value.amount == Decimal("4.9995")
    assert rounded is False


def test_row_correctness_includes_pack_count():
    case = Case(
        "a",
        "acme",
        "real",
        "teach",
        ExpectedValue(Decimal(10), "per_unit_from_pack", 12),
    )
    execution = Execution(
        "p",
        1,
        "d",
        "a",
        output={
            "unit_price": Decimal(10),
            "price_basis": "per_unit_from_pack",
            "pack_size": 24,
        },
    )
    assert grade(case, execution).verdict is Verdict.WRONG_VALUE


def test_zero_in_place_of_nonzero_price_is_critical():
    case = Case("a", "acme", "real", "teach", ExpectedValue(Decimal(10), "as_listed"))
    execution = Execution(
        "p",
        1,
        "d",
        "a",
        output={"unit_price": Decimal(0), "price_basis": "as_listed"},
    )
    assert grade(case, execution).verdict is Verdict.CRITICAL_WRONG_FACTOR


def test_answered_accuracy_excludes_correct_abstentions():
    outcomes = [
        CaseOutcome(str(i), "real", "s", verdict, "", "", "")
        for i, verdict in enumerate(
            [
                Verdict.CORRECT_VALUE,
                Verdict.CORRECT_REVIEW,
                Verdict.CRITICAL_WRONG_FACTOR,
            ]
        )
    ]
    assert summarize(outcomes).accuracy_on_covered == 0.5


def test_missing_and_duplicate_pairs_are_rejected():
    a = CaseOutcome("a", "real", "s", Verdict.CORRECT_VALUE, "", "", "")
    with pytest.raises(ValueError, match="identical"):
        compare_paired([a], [])
    with pytest.raises(ValueError, match="duplicate"):
        compare_paired([a, a], [a])


def test_structural_validation_is_enforced_by_the_runner():
    procedure = library.corrected().model_copy(
        update={"capabilities": ("write_files",)}
    )
    execution = run(
        procedure,
        {},
        context=SupplierContext("a", Locale.US, "USD"),
        tables=library.TABLES,
    )
    assert execution.terminal_state is TerminalState.INVALID
    assert not execution.output


def test_nested_ast_collections_are_immutable():
    with pytest.raises(AttributeError):
        library.corrected().body[0].cases.append(None)


def test_wrong_output_type_faults_and_clears_partial_evidence():
    procedure = library.corrected().model_copy(
        update={
            "body": (
                *library.corrected().body,
                Emit(field="unit_price", value=Literal(value="not money")),
            )
        }
    )
    row = {
        "supplier_sku": "A",
        "description": "Bolt",
        "price": "10",
        "price_unit": "each",
        "pack_size": "",
    }
    execution = run(
        procedure,
        row,
        context=SupplierContext("a", Locale.US, "USD"),
        tables=library.TABLES,
    )
    assert execution.terminal_state is TerminalState.INVALID
    assert execution.output == execution.evidence == {}


def test_recalled_correction_does_not_cross_supplier_locale():
    row = {
        "supplier_sku": "A",
        "description": "Bolt",
        "price": "1.234",
        "price_unit": "each",
        "pack_size": "",
    }
    us = SupplierContext("a", Locale.US, "USD")
    eu = SupplierContext("b", Locale.EU, "EUR")
    fallback = ProcedureRunner(library.naive(), library.TABLES, "naive", "Original")
    recall = LiteralRecall(
        fallback, {recall_key(row, us): {"unit_price": "1", "price_basis": "as_listed"}}
    )
    assert recall.execute(row, eu, "b:A").output["unit_price"] == Decimal(1234)
