import { useEffect, useState } from "react";
import {
  request,
  percent,
  isCorrect,
  type Template,
  type Workspace,
  type Evaluation,
  type Execution,
  type Example,
  type Correction,
} from "./api";

function Output({ value, label }: { value: Execution | null; label: string }) {
  return (
    <div className="output">
      <span className="small-label">{label}</span>
      {!value ? (
        <p>Loading execution…</p>
      ) : value.state === "completed" ? (
        <>
          <strong>{String(value.output.unit_price ?? "No price")}</strong>
          <span>per item</span>
          {value.rounding_applied && (
            <p className="note">Rounded to four decimal places.</p>
          )}
        </>
      ) : (
        <>
          <strong className="review-word">
            {value.state === "invalid" ? "Invalid execution" : "Needs review"}
          </strong>
          <p>{value.fault || value.reviews.map((r) => r.reason).join(" ")}</p>
        </>
      )}
      {value && (
        <details>
          <summary>Why this output?</summary>
          {Object.entries(value.evidence).map(([field, ev]) => (
            <div className="trace" key={field}>
              <b>{field}</b>
              <span>From {ev.source_fields.join(", ") || "a fixed value"}</span>
              <code>{ev.rule_path}</code>
            </div>
          ))}
          {!Object.keys(value.evidence).length && (
            <p className="note">
              No output emitted. Review requests explain the missing context.
            </p>
          )}
        </details>
      )}
    </div>
  );
}
function Source({
  example,
  context,
}: {
  example: Example;
  context: { currency: string; locale: string };
}) {
  return (
    <dl className="source-fields">
      {[
        [
          "Money convention",
          context.currency + " / " + context.locale.toUpperCase() + " decimals",
        ],
        ["Product", example.source.description],
        [
          "Listed price",
          example.source.price + " / " + example.source.price_unit,
        ],
        ["Pack column", example.source.pack_size || "Not supplied"],
      ].map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function download(value: Evaluation) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `skillfoundry-evidence-${value.id}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [exampleId, setExampleId] = useState("acme:AC-100");
  const [challengeId, setChallengeId] = useState("borealis:BO-200");
  const [template, setTemplate] = useState<Template>("corrected");
  const [preview, setPreview] = useState<{
    original: Execution;
    candidate: Execution;
  } | null>(null);
  const [challenge, setChallenge] = useState<{
    original: Execution;
    candidate: Execution;
  } | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [correctionId, setCorrectionId] = useState<string | null>(null);
  const [price, setPrice] = useState("10.0000");
  const [pack, setPack] = useState("12");
  const [basis, setBasis] = useState("per_unit_from_pack");
  const [reason, setReason] = useState(
    "The price is per carton. Divide only when the pack column contains an explicit item count.",
  );
  const [group, setGroup] = useState("real");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [tryPrice, setTryPrice] = useState("120");
  const [tryUnit, setTryUnit] = useState("carton");
  const [tryPack, setTryPack] = useState("12 mm");
  const [tryResult, setTryResult] = useState<Execution | null>(null);
  async function refresh() {
    const data = await request<Workspace>("/workspace");
    setWorkspace(data);
    return data;
  }
  useEffect(() => {
    let live = true;
    request<Workspace>("/workspace")
      .then((data) => {
        if (live) setWorkspace(data);
      })
      .catch((err) => {
        if (live) setError(err.message);
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    let live = true;
    setPreview(null);
    request<{ original: Execution; candidate: Execution }>(
      `/examples/${encodeURIComponent(exampleId)}?template=${template}`,
    )
      .then((data) => {
        if (live) setPreview(data);
      })
      .catch((err) => {
        if (live) setError(err.message);
      });
    return () => {
      live = false;
    };
  }, [exampleId, template]);
  useEffect(() => {
    let live = true;
    setChallenge(null);
    request<{ original: Execution; candidate: Execution }>(
      `/examples/${encodeURIComponent(challengeId)}?template=${template}`,
    )
      .then((data) => {
        if (live) setChallenge(data);
      })
      .catch((err) => {
        if (live) setError(err.message);
      });
    return () => {
      live = false;
    };
  }, [challengeId, template]);
  const example = workspace?.cases.find((c) => c.case_id === exampleId);
  const challengeExample = workspace?.cases.find(
    (c) => c.case_id === challengeId,
  );
  const latestCorrection = workspace?.corrections.find(
    (c) => c.case_id === exampleId,
  );
  function chooseExample(id: string) {
    setExampleId(id);
    setNotice("");
    const c = workspace?.cases.find((c) => c.case_id === id);
    if (c?.expected.kind === "value") {
      setPrice(c.expected.unit_price || "");
      setPack(c.expected.pack_size?.toString() || "");
      setBasis(c.expected.price_basis || "as_listed");
    } else {
      setPrice("");
      setPack("");
      setBasis("per_unit_from_pack");
    }
    setReason("");
  }
  async function saveCorrection(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const correction = await request<Correction>("/corrections", {
        case_id: exampleId,
        expected_revision: latestCorrection?.revision || 0,
        unit_price: price,
        price_basis: basis,
        pack_size: pack ? Number(pack) : null,
        reason,
      });
      setCorrectionId(correction.id);
      setEvaluation(null);
      await refresh();
      setNotice(
        `Correction ${correction.revision} saved. Choose a manual rule and run the challenge suite.`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function evaluate() {
    setBusy(true);
    setError("");
    try {
      const result = await request<Evaluation>("/evaluations", {
        template,
        correction_id: correctionId,
      });
      setEvaluation(result);
      await refresh();
      setNotice(
        "Evaluation saved. Review benefits, regressions and coverage below.",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openEvaluation(id: string) {
    setBusy(true);
    setError("");
    try {
      const result = await request<Evaluation>(`/evaluations/${id}`);
      setEvaluation(result);
      setTemplate(result.template);
      setCorrectionId(result.correction_id);
      setTryResult(null);
      setNotice("Opened an immutable saved evaluation.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!workspace || !example || !challengeExample)
    return (
      <main className="loading">
        <img src="/brand/skillfoundry-mark.svg" width="54" alt="" />
        <h1>SkillFoundry</h1>
        <p role="status">{error || "Opening the pattern workshop…"}</p>
        {error && (
          <button
            onClick={() => void refresh().catch((err) => setError(err.message))}
          >
            Retry connection
          </button>
        )}
      </main>
    );
  const selectedCorrection = workspace.corrections.find(
    (c) => c.id === correctionId,
  );
  const currentMetrics = evaluation?.runs.candidate.metrics;
  const outcomes =
    evaluation?.runs.candidate.outcomes.filter(
      (o) =>
        o.origin === group &&
        (filter === "all" ||
          (filter === "regressions" &&
            evaluation.runs.original.outcomes.some(
              (b) =>
                b.case_id === o.case_id &&
                isCorrect(b.verdict) &&
                !isCorrect(o.verdict),
            )) ||
          (filter === "review" && o.verdict.includes("review"))) &&
        o.case_id.toLowerCase().includes(query.toLowerCase()),
    ) || [];
  return (
    <>
      <a className="skip" href="#evidence">
        Skip to evaluation evidence
      </a>
      <main className="workbench">
        <header className="masthead">
          <a className="brand" href="#teach">
            <img
              src="/brand/skillfoundry-mark.svg"
              width="44"
              height="44"
              alt=""
            />
            <span>
              SkillFoundry<small>Catalog pattern workshop</small>
            </span>
          </a>
          <span className="local-badge">Local workspace</span>
          <a href="#history">Saved work</a>
          <button className="primary" onClick={evaluate} disabled={busy}>
            {busy ? "Working…" : "Run challenge suite"}
          </button>
        </header>
        <section className="title-row">
          <div>
            <p className="context">Supplier catalogs / Procedure 01</p>
            <h1>Unit price normalization</h1>
            <p>A carton count changes a price. A bolt diameter should not.</p>
          </div>
          <div className="fixture-note">
            <b>38 synthetic cases</b>
            <span>32 source fixtures + 6 authored challenges</span>
            <span>No model calls. Manual rules, measured outcomes.</span>
          </div>
        </section>
        {error && (
          <div className="message error" role="alert">
            {error}
            <button onClick={() => setError("")}>Dismiss</button>
          </div>
        )}
        {notice && (
          <p className="message" role="status">
            {notice}
          </p>
        )}
        <section
          id="teach"
          className="teaching-grid"
          aria-label="Example, procedure and challenge"
        >
          <article className="source-pane">
            <div className="pane-heading">
              <span className="step">1</span>
              <h2>Teach from an example</h2>
            </div>
            <label>
              Source example
              <select
                value={exampleId}
                disabled={busy}
                onChange={(e) => chooseExample(e.target.value)}
              >
                {workspace.cases
                  .filter((c) => c.origin === "real")
                  .map((c) => (
                    <option key={c.case_id} value={c.case_id}>
                      {c.case_id} / {c.source.description}
                      {c.split === "holdout" ? " (holdout)" : ""}
                    </option>
                  ))}
              </select>
            </label>
            <Source
              example={example}
              context={workspace.suppliers[example.supplier]}
            />
            <Output
              value={preview?.original || null}
              label="Original procedure"
            />
            <form onSubmit={saveCorrection} className="correction-form">
              <h3>Your correction</h3>
              <div className="form-pair">
                <label>
                  Unit price
                  <input
                    required
                    inputMode="decimal"
                    pattern="[0-9]+(\.[0-9]+)?"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    disabled={busy || example.split === "holdout"}
                  />
                </label>
                <label>
                  Items per pack
                  <input
                    type="number"
                    min="1"
                    max="1000000"
                    value={pack}
                    onChange={(e) => setPack(e.target.value)}
                    disabled={busy || example.split === "holdout"}
                  />
                </label>
              </div>
              <label>
                Price basis
                <select
                  value={basis}
                  onChange={(e) => setBasis(e.target.value)}
                  disabled={busy || example.split === "holdout"}
                >
                  <option value="per_unit_from_pack">
                    Converted from pack
                  </option>
                  <option value="as_listed">Already per item</option>
                </select>
              </label>
              <label>
                When should this correction apply?
                <textarea
                  required
                  minLength={8}
                  maxLength={2000}
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  disabled={busy || example.split === "holdout"}
                />
              </label>
              <button
                className="secondary"
                disabled={busy || example.split === "holdout"}
              >
                Save correction
              </button>
              <p className="note">
                {example.split === "holdout"
                  ? "Holdout examples are excluded from teaching."
                  : latestCorrection
                    ? `Revision ${latestCorrection.revision} saved. Further edits create a new event.`
                    : "Saving keeps the original prediction and your reason."}
              </p>
            </form>
          </article>
          <article className="rule-pane">
            <div className="pane-heading">
              <span className="step">2</span>
              <h2>Define the boundary</h2>
            </div>
            <span className="status proposed">Manually authored candidate</span>
            <fieldset disabled={busy}>
              <legend>Rule template</legend>
              <label
                className={`rule-option ${template === "corrected" ? "selected" : ""}`}
              >
                <input
                  type="radio"
                  name="rule"
                  checked={template === "corrected"}
                  onChange={() => {
                    setTemplate("corrected");
                    setEvaluation(null);
                    setTryResult(null);
                  }}
                />
                <span>
                  <b>Explicit pack rule</b>
                  <small>Respect the price basis and require a count.</small>
                </span>
              </label>
              <label
                className={`rule-option ${template === "overeager" ? "selected" : ""}`}
              >
                <input
                  type="radio"
                  name="rule"
                  checked={template === "overeager"}
                  onChange={() => {
                    setTemplate("overeager");
                    setEvaluation(null);
                    setTryResult(null);
                  }}
                />
                <span>
                  <b>Divide by any number</b>
                  <small>A deliberately over-generalized candidate.</small>
                </span>
              </label>
            </fieldset>
            <div className="rule-logic">
              <p>
                <span>If</span>
                {template === "corrected"
                  ? "Price is quoted per pack"
                  : "Pack column starts with a number"}
              </p>
              {template === "corrected" && (
                <p>
                  <span>And</span>Pack size is an explicit item count
                </p>
              )}
              <p>
                <span>Then</span>Unit price = listed price ÷ count
              </p>
              <p>
                <span>Otherwise</span>
                {template === "corrected"
                  ? "Keep per-item prices; request review for ambiguity"
                  : "Copy the listed price when no number is found"}
              </p>
            </div>
            <Output
              value={preview?.candidate || null}
              label="Candidate preview on this example"
            />
            <div className="teaching-link">
              <b>Teaching evidence</b>
              <p>
                {selectedCorrection
                  ? `${selectedCorrection.case_id}, correction ${selectedCorrection.revision}`
                  : "Bundled AC-100 correction"}
              </p>
              <small>
                {selectedCorrection?.reason ||
                  "120 per carton of 12 becomes 10 per item."}
              </small>
            </div>
            <details>
              <summary>Inspect the structured procedure</summary>
              <pre>
                {JSON.stringify(workspace.procedures[template].ast, null, 2)}
              </pre>
            </details>
            <p className="note">
              A correction is evidence. You choose the rule; no model generates
              it. Preview values have not passed the full suite.
            </p>
          </article>
          <article className="challenge-pane">
            <div className="pane-heading">
              <span className="step">3</span>
              <h2>Test the exception</h2>
            </div>
            <label>
              Challenge example
              <select
                value={challengeId}
                disabled={busy}
                onChange={(e) => setChallengeId(e.target.value)}
              >
                {workspace.cases.map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    {c.case_id} / {c.source.description}
                  </option>
                ))}
              </select>
            </label>
            <Source
              example={challengeExample}
              context={workspace.suppliers[challengeExample.supplier]}
            />
            <div className="boundary-visual">
              <img
                src="/brand/count-or-dimension.svg"
                alt="Twelve items form a count. A 12 millimeter diameter measures one object."
              />
            </div>
            <div className="expected">
              <span className="small-label">Curated expected outcome</span>
              <b>
                {challengeExample.expected.kind === "review"
                  ? `Request review: ${challengeExample.expected.code}`
                  : `${challengeExample.expected.unit_price} per item`}
              </b>
              <small>
                {challengeExample.origin === "generated"
                  ? "Authored challenge"
                  : "Synthetic source fixture"}{" "}
                / {challengeExample.split}
              </small>
            </div>
            <Output
              value={challenge?.candidate || null}
              label="Candidate preview on this challenge"
            />
            <p className="note">
              {challengeExample.rationale ||
                "Compare the price basis and pack column before deciding whether to convert."}
            </p>
            <button className="primary wide" onClick={evaluate} disabled={busy}>
              Evaluate all 38 cases
            </button>
          </article>
        </section>
        <section id="evidence" className="evidence-section">
          <div className="section-title">
            <div>
              <p className="context">Tested behavior</p>
              <h2>What did the rule change?</h2>
            </div>
            {evaluation && (
              <button onClick={() => download(evaluation)}>
                Export evidence JSON
              </button>
            )}
          </div>
          {!evaluation ? (
            <div className="empty">
              <img src="/brand/skillfoundry-mark.svg" width="40" alt="" />
              <h3>The example is a starting point.</h3>
              <p>
                Run the suite to compare this candidate with the original
                procedure and verbatim recall. Critical regressions can block a
                candidate even when its aggregate score improves.
              </p>
            </div>
          ) : (
            <>
              <div
                className={`gate-banner ${evaluation.decision.passed ? "passed" : "blocked"}`}
              >
                <div>
                  <span className="status">
                    {evaluation.decision.passed
                      ? "Gate passed"
                      : "Gate blocked"}
                  </span>
                  <h3>
                    {evaluation.decision.passed
                      ? "The explicit boundary survives this fixture suite."
                      : `${evaluation.decision.new_critical_cases.length} new critical errors. Keep this candidate unapproved.`}
                  </h3>
                  <p>
                    {evaluation.decision.passed
                      ? "This is synthetic evaluation evidence. No production release has been published."
                      : "An aggregate improvement cannot waive critical unit errors."}
                  </p>
                </div>
                <span className="run-id">
                  Saved {new Date(evaluation.created_at).toLocaleString()}
                </span>
              </div>
              <div className="metric-strip">
                <div>
                  <span>Correct decisions, including review</span>
                  <strong>
                    {currentMetrics?.correct} / {currentMetrics?.total}
                  </strong>
                </div>
                <div>
                  <span>Rows handled automatically</span>
                  <strong>
                    {percent(currentMetrics!.covered, currentMetrics!.total)}
                  </strong>
                  <small>
                    {currentMetrics?.covered} emitted values;{" "}
                    {currentMetrics!.total - currentMetrics!.covered} did not
                  </small>
                </div>
                <div>
                  <span>Critical errors</span>
                  <strong>{currentMetrics?.critical}</strong>
                </div>
              </div>
              <div className="evidence-controls">
                <fieldset>
                  <legend>Keep evidence origins separate</legend>
                  <label>
                    <input
                      type="radio"
                      name="group"
                      checked={group === "real"}
                      onChange={() => setGroup("real")}
                    />
                    Source fixtures (32)
                  </label>
                  <label>
                    <input
                      type="radio"
                      name="group"
                      checked={group === "generated"}
                      onChange={() => setGroup("generated")}
                    />
                    Authored challenges (6)
                  </label>
                </fieldset>
              </div>
              <div className="table-scroll">
                <table>
                  <caption>
                    {group === "real"
                      ? "Synthetic supplier-source fixtures"
                      : "Authored counterexamples"}
                    , compared independently
                  </caption>
                  <thead>
                    <tr>
                      <th>Procedure</th>
                      <th>Correct decisions</th>
                      <th>Coverage</th>
                      <th>Critical errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["original", "Original procedure"],
                      ["recall", "Verbatim recall (no model)"],
                      ["candidate", "Selected candidate"],
                    ].map(([key, label]) => {
                      const m = evaluation.groups[group][key];
                      return (
                        <tr key={key}>
                          <th>{label}</th>
                          <td>
                            {m.correct} / {m.total}
                          </td>
                          <td>{percent(m.covered, m.total)}</td>
                          <td>{m.critical}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="gate-grid">
                <div>
                  <h3>Release gate criteria</h3>
                  {evaluation.decision.criteria.map((c) => (
                    <div className="criterion" key={c.code}>
                      <span className={`status ${c.passed ? "pass" : "fail"}`}>
                        {c.passed ? "Pass" : "Blocked"}
                      </span>
                      <div>
                        <b>{c.description}</b>
                        <p>{c.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <aside className="holdout">
                  <h3>Supplier-held-out evidence</h3>
                  <strong>
                    {evaluation.decision.holdout_comparison.candidate_fixed}{" "}
                    fixed /{" "}
                    {evaluation.decision.holdout_comparison.candidate_broke}{" "}
                    broken
                  </strong>
                  <p>
                    Across {evaluation.decision.holdout_comparison.sample_size}{" "}
                    Corvid cases. Exact paired p ={" "}
                    {evaluation.decision.holdout_comparison.p_value.toPrecision(
                      3,
                    )}
                    .
                  </p>
                  <p className="note">
                    The gate asks for positive net performance. This small,
                    visible demo holdout does not establish transfer to unseen
                    suppliers.
                  </p>
                  <details>
                    <summary>Limits of this evidence</summary>
                    <ul>
                      {evaluation.limitations.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  </details>
                </aside>
              </div>
              <div className="case-controls">
                <label>
                  Find a case
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Case ID"
                  />
                </label>
                <label>
                  Show
                  <select
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="all">All outcomes</option>
                    <option value="regressions">New regressions</option>
                    <option value="review">Review outcomes</option>
                  </select>
                </label>
              </div>
              <div className="table-scroll">
                <table>
                  <caption>
                    {outcomes.length} matching outcomes. Select a case to
                    inspect its saved execution.
                  </caption>
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Expected</th>
                      <th>Candidate</th>
                      <th>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {outcomes.map((o) => (
                      <tr key={o.case_id}>
                        <td>
                          <button
                            className="text-button"
                            onClick={() => {
                              setChallengeId(o.case_id);
                              setNotice(o.detail);
                            }}
                          >
                            {o.case_id}
                          </button>
                          <details>
                            <summary>Saved trace</summary>
                            <Output
                              value={evaluation.executions[o.case_id].candidate}
                              label="Execution captured in this evaluation"
                            />
                          </details>
                        </td>
                        <td>{o.expected}</td>
                        <td>{o.actual}</td>
                        <td>
                          <span
                            className={`status ${isCorrect(o.verdict) ? "pass" : "fail"}`}
                          >
                            {o.verdict.replaceAll("_", " ")}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="digest">
                Evidence SHA-256 {evaluation.artifact_digest}
              </p>
            </>
          )}
        </section>
        <section className="try-section">
          <div>
            <h2>Try an ambiguous row</h2>
            <p>
              Explore the selected rule on your own values. This scratchpad uses
              US decimals and USD. It does not modify the evaluation labels.
            </p>
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                setTryResult(
                  await request<Execution>("/try", {
                    template,
                    supplier: "acme",
                    price: tryPrice,
                    price_unit: tryUnit,
                    pack_size: tryPack,
                  }),
                );
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Listed price
              <input
                maxLength={80}
                value={tryPrice}
                onChange={(e) => {
                  setTryPrice(e.target.value);
                  setTryResult(null);
                }}
              />
            </label>
            <label>
              Quoted unit
              <input
                maxLength={40}
                value={tryUnit}
                onChange={(e) => {
                  setTryUnit(e.target.value);
                  setTryResult(null);
                }}
              />
            </label>
            <label>
              Pack text
              <input
                maxLength={40}
                value={tryPack}
                onChange={(e) => {
                  setTryPack(e.target.value);
                  setTryResult(null);
                }}
              />
            </label>
            <button disabled={busy}>Try row</button>
          </form>
          {tryResult && <Output value={tryResult} label="Scratchpad result" />}
        </section>
        <section id="history" className="history">
          <div>
            <h2>Saved corrections</h2>
            {workspace.corrections.length === 0 ? (
              <p className="note">Your first correction will appear here.</p>
            ) : (
              workspace.corrections.map((c) => (
                <div className="history-item" key={c.id}>
                  <b>
                    {c.case_id} / revision {c.revision}
                  </b>
                  <p>
                    {c.unit_price} per item. {c.reason}
                  </p>
                  <small>
                    {c.author} / {new Date(c.created_at).toLocaleString()}
                  </small>
                  <button
                    disabled={busy}
                    onClick={() => {
                      setCorrectionId(c.id);
                      setEvaluation(null);
                      setNotice(
                        "Selected this correction as teaching evidence for the next evaluation.",
                      );
                    }}
                  >
                    Use correction
                  </button>
                </div>
              ))
            )}
          </div>
          <div>
            <h2>Evaluation history</h2>
            {workspace.history.length === 0 ? (
              <p className="note">
                Completed evaluations persist across restarts.
              </p>
            ) : (
              workspace.history.map((h) => (
                <button
                  className="history-run"
                  key={h.id}
                  onClick={() => void openEvaluation(h.id)}
                  disabled={busy}
                >
                  <span>
                    {h.template === "corrected"
                      ? "Explicit pack rule"
                      : "Divide by any number"}
                  </span>
                  <small>{new Date(h.created_at).toLocaleString()}</small>
                  <b>
                    {h.verdict === "PUBLISHABLE" ? "Gate passed" : "Blocked"}
                  </b>
                </button>
              ))
            )}
          </div>
        </section>
        <footer>
          {workspace.engine}. Local, single-user prototype. All supplier data is
          synthetic. No AI proposer or production publishing.
          <details>
            <summary>Fixture identity</summary>
            <code>{workspace.fixture_digest}</code>
          </details>
        </footer>
      </main>
    </>
  );
}
