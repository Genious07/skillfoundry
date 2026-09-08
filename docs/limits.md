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
  real cases across 3 synthetic suppliers, labelled by one person, the author.
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

## Next steps to make this a product

1. Measure expert correction time on real corrections, because the value
   proposition depends on it.
2. Recruit three catalog specialists and give them the prototype task without
   coaching, per the blueprint's validation section.
3. Add persistence, the job runner, and organization ownership, so more than one
   person can use it.
4. Add the three pane teaching interface over the existing evidence records.
5. Only then add a model backed rule proposer, measured against the same gate.
