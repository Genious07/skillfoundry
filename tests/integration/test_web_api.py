"""Real interpreter, evaluator and SQLite persistence across the HTTP boundary."""


import pytest
from fastapi.testclient import TestClient
from skillfoundry_api.app import create_app, digest

HEADERS = {"X-SkillFoundry-Client": "workbench"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "workshop.db")) as client:
        yield client


def correction(client, **overrides):
    body = {
        "case_id": "acme:AC-100",
        "expected_revision": 0,
        "unit_price": "10.0000",
        "price_basis": "per_unit_from_pack",
        "pack_size": 12,
        "reason": "Divide only explicit pack counts.",
    }
    return client.post("/api/corrections", headers=HEADERS, json=body | overrides)


def test_complete_teaching_loop_and_immutable_export(client):
    saved = correction(client)
    assert saved.status_code == 201
    assert saved.json()["original"]["output"]["unit_price"] == "120"
    result = client.post(
        "/api/evaluations",
        headers=HEADERS,
        json={"template": "corrected", "correction_id": saved.json()["id"]},
    )
    assert result.status_code == 201
    body = result.json()
    assert body["decision"]["passed"] is True
    assert body["runs"]["candidate"]["metrics"]["correct"] == 38
    assert body["runs"]["candidate"]["metrics"]["correct_covered"] == 31
    assert body["groups"]["real"]["candidate"]["total"] == 32
    assert body["groups"]["generated"]["candidate"]["total"] == 6
    assert body["artifact_digest"] == digest(
        {k: v for k, v in body.items() if k != "artifact_digest"}
    )
    correction(client, expected_revision=1, unit_price="9")
    assert client.get("/api/evaluations/" + body["id"]).json() == body


def test_overgeneralization_remains_blocked(client):
    body = client.post(
        "/api/evaluations", headers=HEADERS, json={"template": "overeager"}
    ).json()
    assert body["decision"]["passed"] is False
    assert len(body["decision"]["new_critical_cases"]) == 8
    assert (
        body["executions"]["borealis:BO-200"]["candidate"]["output"]["unit_price"]
        == "0.8333"
    )


def test_correction_survives_restart_and_conflicting_tab_is_rejected(tmp_path):
    path = tmp_path / "state.db"
    with TestClient(create_app(path)) as client:
        saved = correction(client).json()
        assert correction(client).status_code == 409
    with TestClient(create_app(path)) as client:
        assert client.get("/api/workspace").json()["corrections"][0] == saved


def test_holdout_cannot_be_taught(client):
    assert correction(client, case_id="corvid:CO-300").status_code == 422


def test_unknown_and_extra_fields_fail_closed(client):
    assert correction(client, case_id="missing").status_code == 404
    assert correction(client, force=True).status_code == 422
    assert (
        client.post(
            "/api/evaluations", headers=HEADERS, json={"template": "arbitrary_python"}
        ).status_code
        == 422
    )
    assert client.get("/api/evaluations/not-found").status_code == 404


def test_cross_origin_and_simple_browser_mutations_are_blocked(client):
    assert (
        client.post("/api/evaluations", json={"template": "corrected"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/evaluations",
            headers=HEADERS | {"Origin": "https://example.org"},
            json={"template": "corrected"},
        ).status_code
        == 403
    )
    assert (
        client.get("/api/workspace", headers={"Host": "evil.example"}).status_code
        == 400
    )


def test_request_size_limit(client):
    assert (
        client.post(
            "/api/corrections", headers=HEADERS, content=b"x" * 131073
        ).status_code
        == 413
    )


def test_scratchpad_runs_actual_interpreter_without_changing_suite(client):
    before = client.get("/api/workspace").json()["fixture_digest"]
    base = {
        "template": "corrected",
        "supplier": "acme",
        "price": "120",
        "price_unit": "carton",
        "pack_size": "12 mm",
    }
    body = client.post("/api/try", headers=HEADERS, json=base).json()
    assert body["state"] == "needs_review"
    assert body["output"] == {}
    body = client.post(
        "/api/try", headers=HEADERS, json=base | {"pack_size": "12"}
    ).json()
    assert body["output"]["unit_price"] == "10.0000"
    assert client.get("/api/workspace").json()["fixture_digest"] == before
