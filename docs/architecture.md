# Architecture

## The pipeline

```text
supplier feed + declared decimal convention
                  |
        source rows (strings, untouched)
                  |
        procedure AST (typed, validated)
                  |
        structural validation and capability check
                  |
        deterministic interpreter (trusted operators only)
                  |
   output row + field evidence + review requests
                  |
        independent grader against reviewer labels
                  |
   metrics, paired comparison, release gate decision
```

Nothing crosses a layer boundary in the other direction. The grader cannot be
edited by a procedure. The interpreter cannot execute anything a procedure
author wrote in Python. Reviewer labels are read by the grader and never by the
interpreter.

## Why the procedure is an AST rather than code

The product's whole promise is that a correction becomes something a reviewer
can inspect, test, and publish. That requires the procedure to be inspectable
data with a fixed operator vocabulary.

It also closes the obvious hole. In a later milestone a language model proposes
rules. If a proposal were Python, accepting one would mean executing model
written code against a supplier catalog. Because a proposal is instead a tree
of eight known operators, an unsafe proposal fails schema validation before
anything runs. `extra="forbid"` on every node means a proposal carrying an
unexpected key is rejected outright, and there is a test for that.

## Validation before execution

`Procedure.validate_structure` is the safety boundary. It checks:

| Check | Why it exists |
|---|---|
| `operator_not_permitted` | A procedure declares which operators it may use. Using more is a privilege escalation. |
| `unknown_operator` | An allowed set naming an operator that does not exist is a malformed declaration. |
| `undeclared_input` | Reading a column outside the declared input schema is undeclared data access. |
| `undeclared_output` | Writing a field outside the output schema breaks the downstream contract. |
| `unresolved_reference` | A binding used before it is defined would be an execution fault. |
| `undeclared_table` / `missing_table` | Lookups must declare their vocabulary so a reviewer can audit it. |
| `capability_not_supported` | Milestone A is read only by construction. |
| `no_abstention_path` | A procedure that cannot decline will guess on an ambiguous row. |

## Determinism and what is not deterministic

Given the same procedure, row, tables, and supplier context, execution produces
identical output. There is no clock, no randomness, and no model call in the
execution path. A test runs the same case 50 times and compares.

This holds because milestone A has no model backed operator. When one is added,
replay becomes potentially variable and the execution record will have to carry
the provider and model configuration. That is a stated future change, not a
property this release already has.

## Evidence

Every emitted field records the source columns it depended on and the rule path
that produced it. `Ref` bindings propagate their own source columns, so a unit
price derived through two bindings still names `price` and `pack_size` rather
than naming the bindings. This is what makes the `explain` command possible and
what the three pane interface will render in a later milestone.

## Why two baselines

Baseline 1 is the original procedure. Baseline 2 recalls the taught correction
verbatim and falls back to baseline 1 elsewhere.

Without baseline 2, a candidate that memorized the single taught row would show
an improvement and could be published. Requiring a candidate to beat verbatim
recall is what forces it to encode a condition rather than a fact. This is the
criterion that a complex learning system has to earn.

Baseline 2 is deliberately generous: it never misapplies the correction and
never forgets it. A prompted language model would not guarantee either. It is a
lower bound, and it is not a model.

## Why the split is by supplier

Catalog rows within one supplier are near duplicates of each other. A random
row split leaks the answer across the boundary. The `corvid` supplier is held
out whole, uses a different decimal convention from the teaching suppliers, and
is absent from the teaching set.
