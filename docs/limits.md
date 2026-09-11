# What is and is not established here

This document exists so that nobody, including the author later, mistakes a
fixture result for a product claim.

## Established

- The interpreter is deterministic over the fixture space, verified by repeated
  execution.
- Branch conditions in all three library procedures are mutually exclusive over
  a 400 row cross product of price units, pack sizes, and prices.
- Money arithmetic is exact decimal. Unit price division is exact when it
  divides evenly and flags rounding when it does not.
- A number carrying any unit in the dimension vocabulary is never read as a
  count. Every such unit has a test.
- Structural validation rejects each of the eight defect classes listed in
  `architecture.md`, each with a test.
- An unguarded conversion faults and discards its partial output rather than
  emitting a plausible wrong price.
- The release gate blocks a candidate that improves on the holdout while
  introducing critical unit errors, and acknowledging the regressions does not
  unblock it.

## Not established

- **That the rule works on real supplier data.** The fixtures are invented. 32
  source fixtures across 3 synthetic suppliers, labelled by one person, the author.
  There is no inter annotator agreement because there was one annotator.
- **That the approach transfers.** The holdout comparison has 10 cases and 6
  discordant pairs. The exact two sided p value of 0.0312 is correctly computed
  and badly underpowered. It rules out very little.
- **That a model can propose these rules.** No model runs anywhere in this
  release. The AST and validator are the safety scaffolding for that step, and
  the harness is here to judge proposals when they arrive, but the proposer is
  future work.
- **That teaching effort is lower than writing the rule by hand.** The
  blueprint calls for measuring expert correction time. Nothing here measures
  it, and it is plausible that authoring the condition directly is cheaper than
  teaching it. That is an open question, not a solved one.
- **That the abstention rate is acceptable.** The candidate declines 7 of 38
  cases. Whether a specialist prefers 18 percent of rows landing in a review
  queue over a small number of silent errors is a question for a specialist,
  and no specialist has been asked.

## The critical error threshold

A unit price wrong by a factor of 2 or more is classified critical, because the
smallest genuine pack size is two, so an error of that size is the signature of
a pack factor applied to the wrong row. A price wrong by 1.5x is graded as an
ordinary wrong value.

This is a product judgement rather than a derived constant. It is defined once
in `metrics.py` as `CRITICAL_RATIO` and pinned by a boundary test.

## Local workbench boundary

The React interface and FastAPI API now persist corrections and evaluation
snapshots in SQLite. Two manual templates execute through the trusted
interpreter. The scratchpad accepts a bounded single row. No model generates a
rule, no file importer exists, and the displayed structured procedure is read-only.
Saved artifacts include the procedure, lookup tables, supplier conventions,
fixture labels and inputs, teaching evidence, execution traces, metrics and
digests. A digest detects accidental alteration; it is not a signed release.

The 38-case suite runs synchronously. There is no worker, tenant isolation,
authentication, Postgres deployment, production release registry, or arbitrary
procedure upload. The server is for a single user on localhost. This is a
bounded Milestone B teaching loop, not completion of milestones B through F.

The gate requires positive paired net improvement, not a p-value threshold.
Its supplier holdout is visible demo data and cannot validate unseen-data
transfer. The internal origin label `real` means synthetic supplier-source
fixture, not observed customer data.

## Next steps to make this a product

1. Obtain independently labeled real supplier examples and a blind holdout;
   measure specialist correction time and acceptable review workload.
2. Add reviewed CSV import and an editable, validated rule authoring workflow.
3. Evaluate an actual model proposer against both a prompted-model baseline and
   verbatim recall. Keep the critical-error veto and separate challenge results.
4. Add identities, organization isolation, asynchronous jobs, database migrations,
   and a signed versioned release artifact before shared deployment.
