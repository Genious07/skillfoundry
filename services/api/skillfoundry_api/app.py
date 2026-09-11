"""Bounded local teaching loop with append-only corrections and evaluation snapshots.

No model or arbitrary submitted program is executed. Candidates are two manually
selected, trusted library templates. The small fixed suite runs synchronously.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from skillfoundry_domain import library
from skillfoundry_domain.interpreter import run
from skillfoundry_evaluation.baselines import (
    LiteralRecall,
    ProcedureRunner,
    load_corrections,
    recall_key,
)
from skillfoundry_evaluation.metrics import summarize
from skillfoundry_evaluation.report import evaluate_gate
from skillfoundry_evaluation.runner import evaluate, load_fixtures
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parents[3]
ENGINE = "skillfoundry-0.2.0"


def serial(value):
    return jsonable_encoder(value, custom_encoder={Decimal: str})


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CorrectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(max_length=100)
    expected_revision: int = Field(ge=0)
    unit_price: str = Field(pattern=r"^[0-9]{1,20}(\.[0-9]{1,8})?$", max_length=29)
    price_basis: Literal["as_listed", "per_unit_from_pack"]
    pack_size: int | None = Field(default=None, ge=1, le=1000000)
    reason: str = Field(min_length=8, max_length=2000)
    author: str = Field(default="Local reviewer", min_length=1, max_length=100)


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Literal["corrected", "overeager"]
    correction_id: str | None = None


class TryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Literal["naive", "corrected", "overeager"]
    supplier: Literal["acme", "borealis", "corvid"]
    description: str = Field(default="My catalog item", min_length=1, max_length=200)
    price: str = Field(max_length=80)
    price_unit: str = Field(max_length=40)
    pack_size: str = Field(max_length=40)


def create_app(db_path: str | Path | None = None, fixture_root: Path | None = None):
    app = FastAPI(title="SkillFoundry local workbench", version="0.2.0")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    path = Path(db_path or os.environ.get("SKILLFOUNDRY_DB", ROOT / "skillfoundry.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    fixtures = load_fixtures(fixture_root or ROOT / "fixtures/demo")
    cases = {c.case_id: c for c in fixtures.all_cases}
    source_snapshot = serial(
        [
            asdict(c)
            | {
                "source": fixtures.rows_by_case[c.case_id],
                "context": asdict(fixtures.suppliers[c.supplier]),
            }
            for c in fixtures.all_cases
        ]
    )
    fixture_digest = digest(source_snapshot)

    @contextmanager
    def database(write=False):
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    with database() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError(
                "Unsupported database schema version; restore or migrate explicitly"
            )
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS corrections (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, revision INTEGER NOT NULL,
                payload TEXT NOT NULL, UNIQUE(case_id, revision));
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            PRAGMA user_version=1;
        """)

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            if request.headers.get("x-skillfoundry-client") != "workbench":
                return JSONResponse(
                    {"detail": "Local workbench client header required"},
                    status_code=403,
                )
            origin = request.headers.get("origin")
            if origin and origin not in {
                "http://localhost:8020",
                "http://127.0.0.1:8020",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            }:
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            size = (
                int(request.headers.get("content-length", "0"))
                if request.headers.get("content-length", "0").isdigit()
                else 131073
            )
            if size > 131072:
                return JSONResponse(
                    {"detail": "Request exceeds 128 KiB"}, status_code=413
                )
            chunks = bytearray()
            async for chunk in request.stream():
                chunks.extend(chunk)
                if len(chunks) > 131072:
                    return JSONResponse(
                        {"detail": "Request exceeds 128 KiB"}, status_code=413
                    )
            request._body = bytes(chunks)
        return await call_next(request)

    def execution(template, case_id):
        case = cases.get(case_id)
        if case is None:
            raise HTTPException(404, "Example not found")
        result = run(
            library.load(template),
            fixtures.rows_by_case[case_id],
            tables=library.TABLES,
            context=fixtures.suppliers[case.supplier].context,
            row_id=case_id,
        )
        return serial(asdict(result) | {"state": result.terminal_state.value})

    @app.get("/api/workspace")
    def workspace():
        with database() as conn:
            corrections = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT payload FROM corrections ORDER BY rowid DESC"
                )
            ]
            history = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT payload FROM evaluations ORDER BY rowid DESC LIMIT 30"
                )
            ]
        return {
            "engine": ENGINE,
            "fixture_digest": fixture_digest,
            "suppliers": serial(fixtures.suppliers),
            "cases": [
                {
                    "case_id": c.case_id,
                    "supplier": c.supplier,
                    "origin": c.origin,
                    "split": c.split,
                    "rationale": c.rationale,
                    "source": fixtures.rows_by_case[c.case_id],
                    "expected": serial(c.expect),
                }
                for c in fixtures.all_cases
            ],
            "procedures": {
                key: {
                    "name": library.load(key).name,
                    "description": library.load(key).description,
                    "digest": library.load(key).digest,
                    "ast": json.loads(library.load(key).canonical_json()),
                }
                for key in library.REGISTRY
            },
            "corrections": corrections,
            "history": [
                {
                    "id": h["id"],
                    "created_at": h["created_at"],
                    "template": h["template"],
                    "verdict": h["decision"]["verdict"],
                    "correction_id": h["correction_id"],
                }
                for h in history
            ],
        }

    @app.get("/api/examples/{case_id}")
    def example(
        case_id: str, template: Literal["naive", "corrected", "overeager"] = "corrected"
    ):
        return {
            "original": execution("naive", case_id),
            "candidate": execution(template, case_id),
        }

    @app.post("/api/corrections", status_code=201)
    def save_correction(body: CorrectionInput):
        case = cases.get(body.case_id)
        if not case:
            raise HTTPException(404, "Example not found")
        if case.split == "holdout":
            raise HTTPException(
                422, "Holdout examples cannot be used as teaching corrections"
            )
        if body.price_basis == "per_unit_from_pack" and body.pack_size is None:
            raise HTTPException(422, "A converted price needs an explicit pack size")
        if not body.reason.strip():
            raise HTTPException(422, "Describe when this correction applies")
        with database(write=True) as conn:
            revision = conn.execute(
                "SELECT COALESCE(MAX(revision),0) FROM corrections WHERE case_id=?",
                (body.case_id,),
            ).fetchone()[0]
            if body.expected_revision != revision:
                raise HTTPException(
                    409,
                    "This example changed in another tab. Reload its correction before saving.",
                )
            payload = body.model_dump() | {
                "id": uuid.uuid4().hex,
                "revision": revision + 1,
                "created_at": datetime.now(UTC).isoformat(),
                "source": fixtures.rows_by_case[body.case_id],
                "source_digest": digest(fixtures.rows_by_case[body.case_id]),
                "original": execution("naive", body.case_id),
                "fixture_digest": fixture_digest,
            }
            conn.execute(
                "INSERT INTO corrections VALUES (?,?,?,?)",
                (payload["id"], body.case_id, revision + 1, json.dumps(payload)),
            )
        return payload

    @app.post("/api/evaluations", status_code=201)
    def create_evaluation(body: EvaluationInput):
        correction = None
        with database() as conn:
            if body.correction_id:
                found = conn.execute(
                    "SELECT payload FROM corrections WHERE id=?", (body.correction_id,)
                ).fetchone()
                if found is None:
                    raise HTTPException(404, "Correction not found")
                correction = json.loads(found[0])
                if correction["fixture_digest"] != fixture_digest:
                    raise HTTPException(
                        409, "Correction belongs to different fixture inputs"
                    )
        original = ProcedureRunner(
            library.load("naive"), library.TABLES, "original", "Original procedure"
        )
        corrections = load_corrections(
            fixtures.root / "teaching.jsonl", fixtures.rows_by_case
        )
        if correction:
            corrections[
                recall_key(
                    correction["source"],
                    fixtures.suppliers[cases[correction["case_id"]].supplier].context,
                )
            ] = {
                key: correction[key]
                for key in ("unit_price", "price_basis", "pack_size")
            }
        recall = LiteralRecall(original, corrections)
        candidate = ProcedureRunner(
            library.load(body.template),
            library.TABLES,
            "candidate",
            "Candidate procedure",
        )
        runners = {"original": original, "recall": recall, "candidate": candidate}
        runs = {
            key: evaluate(runner, fixtures.all_cases, fixtures)
            for key, runner in runners.items()
        }
        holdout = fixtures.split("holdout", origin="real")
        decision = evaluate_gate(
            original=runs["original"],
            recall=runs["recall"],
            candidate=runs["candidate"],
            original_holdout=evaluate(original, holdout, fixtures),
            candidate_holdout=evaluate(candidate, holdout, fixtures),
        )
        snapshot = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
            "engine": ENGINE,
            "template": body.template,
            "correction_id": body.correction_id,
            "correction": correction,
            "fixture_digest": fixture_digest,
            "procedure": json.loads(candidate.procedure.canonical_json()),
            "procedure_digest": candidate.procedure.digest,
            "tables": library.TABLES,
            "source_snapshot": source_snapshot,
            "teaching_snapshot": corrections,
            "decision": serial(
                asdict(decision)
                | {"passed": decision.passed, "verdict": decision.verdict}
            ),
            "runs": {
                key: serial(
                    asdict(result)
                    | {
                        "rates": {
                            "row_accuracy": result.metrics.row_accuracy,
                            "coverage": result.metrics.coverage,
                            "abstention_rate": result.metrics.abstention_rate,
                            "accuracy_on_covered": result.metrics.accuracy_on_covered,
                        }
                    }
                )
                for key, result in runs.items()
            },
            "groups": {
                origin: {
                    key: serial(
                        asdict(
                            summarize(
                                [o for o in result.outcomes if o.origin == origin]
                            )
                        )
                    )
                    for key, result in runs.items()
                }
                for origin in ("real", "generated")
            },
            "executions": {
                case.case_id: {
                    "original": execution("naive", case.case_id),
                    "candidate": execution(body.template, case.case_id),
                }
                for case in fixtures.all_cases
            },
            "limitations": [
                "All 38 cases are synthetic; source fixtures and authored challenges have separate totals.",
                "Rules are hand-authored templates. A saved correction does not generate a rule.",
                "The holdout is a teaching exclusion, not a blind study: demo source and labels are inspectable.",
                "A positive net holdout score is the current gate criterion, not proof of statistical significance.",
                "This is an evaluation evidence bundle, not a published or signed production release.",
            ],
        }
        snapshot["artifact_digest"] = digest(snapshot)
        with database(write=True) as conn:
            conn.execute(
                "INSERT INTO evaluations VALUES (?,?,?)",
                (snapshot["id"], snapshot["created_at"], json.dumps(snapshot)),
            )
        return snapshot

    @app.get("/api/evaluations/{evaluation_id}")
    def get_evaluation(evaluation_id: str):
        with database() as conn:
            row = conn.execute(
                "SELECT payload FROM evaluations WHERE id=?", (evaluation_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Evaluation not found")
        return json.loads(row[0])

    @app.post("/api/try")
    def try_row(body: TryInput):
        values = {
            "supplier_sku": "TRY-001",
            "description": body.description,
            "price": body.price,
            "price_unit": body.price_unit,
            "pack_size": body.pack_size,
        }
        result = run(
            library.load(body.template),
            values,
            tables=library.TABLES,
            context=fixtures.suppliers[body.supplier].context,
            row_id="try:001",
        )
        return serial(asdict(result) | {"state": result.terminal_state.value})

    @app.get("/api/health")
    def health():
        with database() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "engine": ENGINE}

    dist = ROOT / "apps/web/dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
        app.mount("/brand", StaticFiles(directory=dist / "brand"), name="brand")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


def main():
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8020)
