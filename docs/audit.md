# SkillFoundry audit, 10 September 2026

The initial checkout passed 135 tests and reproduced the reported fixture
scores. It had no frontend, API, or persistence. The handoff described
Milestone A accurately, but a complete frontend-to-backend product did not exist.

## Correctness defects repaired

- Money parsing removed arbitrary characters, allowing `1e3` to become 13 and
  `10/12` to become 1012. Parsing now validates the entire numeric token, declared
  decimal convention, grouping and currency; ambiguous input is refused.
- Decimal division inherited ambient precision. It now uses a local precision
  context and retains explicit four-place rounding evidence.
- Frozen AST nodes contained mutable nested lists. Branch and condition sequences
  are now immutable tuples. Execution always runs structural validation.
- Runtime output types could disagree with the declared schema. Such executions
  now fault and discard partial values and evidence. Review paths discard them too.
- Grading could accept the wrong pack count. All expected output fields now count
  toward correctness. Covered accuracy no longer includes correct abstentions in
  its numerator. Zero versus nonzero price errors are critical.
- Paired comparisons could silently drop missing cases or collapse duplicates.
  Comparisons and gate evaluation now reject mismatched case sets.
- Verbatim recall ignored supplier context. Keys now include supplier, currency,
  decimal convention and row identity. Holdout rows cannot become teaching data.
- Fixture ingestion now checks identity, origin, supplier grouping and reviewed
  labels. CLI explanation resolves generated-case supplier context correctly.
- Small p-values no longer print as zero. Documentation removes the unsupported
  claim that literal recall is a lower bound on a prompted model.

## Added usable workflow

Three panes place source evidence, a manual candidate and a counterexample side
by side. SQLite stores append-only corrections and evaluation snapshots. Stale
correction revisions return conflict errors. Saved runs preserve their input,
procedure, teaching and output evidence independently of later corrections.

Original SVG assets illustrate the difference between a count and a dimension.
Violet denotes proposed logic, green passing measured evidence, and red blocked
evidence. Local fonts, responsive columns, semantic controls, focus indicators,
source/challenge separation and explicit currency conventions support inspection.

## Verification

162 Python tests and four frontend transport/display tests pass locally. The
frontend production build succeeds. Browser checks cover correction save, both
candidate evaluations, saved history, regression inspection and scratchpad
abstention. The accepted candidate retains 38/38 correct decisions, 31 emitted
values and zero critical errors. The tempting candidate has 15 critical errors,
eight newly introduced, and is blocked. These are synthetic fixture results.

See limits.md for unbuilt product capabilities and the next recommended work.
