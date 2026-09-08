"""Validation must reject a malformed or over privileged proposal.

Every test here builds a procedure that a careless proposer could plausibly
produce, then asserts that validation refuses it before execution.
"""

from __future__ import annotations

import pytest

from skillfoundry_domain import library
from skillfoundry_domain.ast import (
    Binding,
    Branch,
    BranchCase,
    Compare,
    Emit,
    Literal,
    Lookup,
    ParseMoney,
    ReadField,
    Ref,
    RequestReview,
)
from skillfoundry_domain.procedure import FieldSpec, Procedure

BASE = dict(
    procedure_id="test.proc",
    revision=1,
    name="test",
    input_schema=(FieldSpec(name="price", kind="money"),),
    output_schema=(FieldSpec(name="unit_price", kind="money"),),
)

_ALWAYS = Compare(comparison="is_blank", left=Literal(value=""))
_REVIEW = RequestReview(code="x", reason="needs a human")


def _codes(procedure, tables=None):
    return {issue.code for issue in procedure.validate_structure(tables or {}).issues}


def test_every_library_procedure_validates():
    for name in library.REGISTRY:
        report = library.load(name).validate_structure(library.TABLES)
        assert report.ok, f"{name} failed validation: {report.describe()}"


def test_using_an_operator_outside_the_allowed_set_is_rejected():
    procedure = Procedure(
        **BASE,
        allowed_operators=frozenset({"read_field", "emit", "branch", "compare", "request_review"}),
        bindings=(Binding(name="money", value=ParseMoney(source=ReadField(field="price"))),),
        body=(Branch(cases=[BranchCase(when=_ALWAYS, body=[_REVIEW])], otherwise=[_REVIEW]),),
    )
    assert "operator_not_permitted" in _codes(procedure)


def test_an_unknown_operator_name_in_the_allowed_set_is_rejected():
    procedure = Procedure(
        **BASE,
        allowed_operators=frozenset({"read_field", "emit", "branch", "compare", "request_review", "exec_python"}),
        body=(Branch(cases=[BranchCase(when=_ALWAYS, body=[_REVIEW])], otherwise=[_REVIEW]),),
    )
    assert "unknown_operator" in _codes(procedure)


def test_reading_a_field_outside_the_input_schema_is_rejected():
    procedure = Procedure(
        **BASE,
        body=(
            Branch(
                cases=[BranchCase(when=_ALWAYS, body=[Emit(field="unit_price", value=ReadField(field="secret_cost"))])],
                otherwise=[_REVIEW],
            ),
        ),
    )
    assert "undeclared_input" in _codes(procedure)


def test_writing_a_field_outside_the_output_schema_is_rejected():
    procedure = Procedure(
        **BASE,
        body=(
            Branch(
                cases=[BranchCase(when=_ALWAYS, body=[Emit(field="margin", value=ReadField(field="price"))])],
                otherwise=[_REVIEW],
            ),
        ),
    )
    assert "undeclared_output" in _codes(procedure)


def test_referencing_an_undefined_binding_is_rejected():
    procedure = Procedure(
        **BASE,
        body=(
            Branch(
                cases=[BranchCase(when=_ALWAYS, body=[Emit(field="unit_price", value=Ref(name="ghost"))])],
                otherwise=[_REVIEW],
            ),
        ),
    )
    assert "unresolved_reference" in _codes(procedure)


def test_a_binding_referencing_a_later_binding_is_rejected():
    procedure = Procedure(
        **BASE,
        bindings=(
            Binding(name="first", value=Ref(name="second")),
            Binding(name="second", value=ReadField(field="price")),
        ),
        body=(Branch(cases=[BranchCase(when=_ALWAYS, body=[_REVIEW])], otherwise=[_REVIEW]),),
    )
    assert "unresolved_reference" in _codes(procedure)


def test_an_undeclared_lookup_table_is_rejected():
    procedure = Procedure(
        **BASE,
        required_tables=(),
        body=(
            Branch(
                cases=[
                    BranchCase(
                        when=_ALWAYS,
                        body=[Emit(field="unit_price", value=Lookup(table="secret_map", key=ReadField(field="price")))],
                    )
                ],
                otherwise=[_REVIEW],
            ),
        ),
    )
    assert "undeclared_table" in _codes(procedure)


def test_a_declared_but_unsupplied_lookup_table_is_rejected():
    procedure = Procedure(
        **BASE,
        required_tables=("unit_kind",),
        body=(
            Branch(
                cases=[
                    BranchCase(
                        when=_ALWAYS,
                        body=[Emit(field="unit_price", value=Lookup(table="unit_kind", key=ReadField(field="price")))],
                    )
                ],
                otherwise=[_REVIEW],
            ),
        ),
    )
    assert "missing_table" in _codes(procedure, tables={})


def test_a_procedure_with_no_way_to_decline_is_rejected():
    procedure = Procedure(
        **BASE,
        body=(
            Branch(
                cases=[BranchCase(when=_ALWAYS, body=[Emit(field="unit_price", value=ReadField(field="price"))])],
                otherwise=[Emit(field="unit_price", value=Literal(value=0))],
            ),
        ),
    )
    assert "no_abstention_path" in _codes(procedure)


def test_requesting_a_capability_beyond_read_only_is_rejected():
    procedure = Procedure(
        **BASE,
        capabilities=("read_only", "write_catalog"),
        body=(Branch(cases=[BranchCase(when=_ALWAYS, body=[_REVIEW])], otherwise=[_REVIEW]),),
    )
    assert "capability_not_supported" in _codes(procedure)


def test_extra_fields_in_a_proposed_node_are_refused_by_the_schema():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ReadField.model_validate({"op": "read_field", "field": "price", "shell": "rm -rf /"})


def test_the_digest_is_stable_across_rebuilds_and_changes_with_content():
    a = library.load("corrected")
    b = library.load("corrected")
    assert a.digest == b.digest
    assert a.digest != library.load("overeager").digest
    assert a.digest != library.load("naive").digest


def test_the_two_revision_two_candidates_are_distinguishable_by_digest_alone():
    # Both claim revision 2 of the same procedure id. Only the digest separates
    # the accepted rule from the rejected one, which is why releases pin it.
    corrected, overeager = library.load("corrected"), library.load("overeager")
    assert corrected.revision == overeager.revision == 2
    assert corrected.procedure_id == overeager.procedure_id
    assert corrected.digest != overeager.digest
