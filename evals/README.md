# Evaluations

Measurements, not tests. Nothing here passes or fails; it produces the numbers a
change has to be argued with.

## `skill_matching.json`

Twenty-six hand-labelled cases for the rule that decides whether a resume meets a
requirement (`cover` and `evidence` in `app/services/matching.py`, defect W-1).

Each case fixes both lists -- the requirements of a posting, and what the resume
evidences -- and states which requirements a careful reader would call met.
Extraction is deliberately excluded: measuring the matcher through the extractor
would mix two qualities into one number, and only one of them is being changed.

Fifteen cases are software roles and eleven are not: warehouse, kitchen, garage,
shop floor, care home, delivery, training, accounts, hotel. The application is
meant for a mechanic and a cook as much as for a backend engineer, and a rule
tuned on one vocabulary fails quietly on the others -- as the numbers below show.

The labels are a judgement, not data. Read them before trusting anything computed
from them; a case you disagree with is a case worth arguing about, because the
disagreement is the specification. Two are deliberately arguable:
`forklift-hours-imply-the-licence` reads a credential out of experience, and
`workshops-answer-public-speaking` sits in open tension with
`mentoring-and-leadership`, where the same requirement is labelled unmet.

```bash
uv run python -m scripts.eval_skill_matching
```

## Baseline, 2026-09-02 (deterministic rule, before any semantic matching)

| Metric | All 26 | Software only | Everything else |
|---|---|---|---|
| precision | 1.000 | 1.000 | 1.000 |
| recall | 0.596 | 0.654 | 0.524 |
| f1 | 0.747 | 0.791 | 0.688 |
| mean score gap | 0.279 | 0.250 | 0.318 |

**The rule is measurably worse outside software** -- half of what a tradesperson
proves is reported as a gap. Nothing about it is IT-specific by design; it simply
had only IT vocabulary to fail on until now.

Nineteen misses, every one a synonym, a spelling or an implication the rule cannot
see: `postgresql` for `sql`, Excel for `spreadsheets`, SAP for `erp systems`, a
till for `pos systems`, HACCP for `food safety`, forklift hours for the `forklift
licence`, workshops for `public speaking`, Go for `golang`, `Dockerfiles` for
`docker`, `licence` for `license`, and `diagnostics`/`brakes` for `vehicle
diagnostics`/`brake systems` -- where the resume has one word of a two-word
requirement and the rule needs both.

Precision at 1.000 is the number to defend. A matcher that awards more will raise
recall; whether it is an improvement depends on what it does to this column.
`nothing-in-common`, `care-is-not-medication`, `category-b-is-not-category-c` and
`java-is-not-javascript` are the cases that will show a regression first.

## `extraction.json`

Eight (posting, resume) pairs from one trade each -- garage, kitchen, warehouse,
care home, office, delivery, shop, and one software team -- for the two prompts
that read a list of skills out of a text (`job-post-skills`, `resume-skills`).

This one **calls a real model**: it costs money, needs `ANTHROPIC_API_KEY` and
answers differently from run to run, which is what `--runs` is for. A term that
survives one run in three is not extracted, it is guessed.

Each side of a pair carries `must_include` (a reader would insist on it),
`must_exclude` (a perk, an employer name, a date, or a skill the text never
claims) and the pair carries `must_agree` -- terms both sides have to produce in
a form `cover()` can link. That last list is the point: a posting saying
`postgresql` and a resume saying `postgres` are two correct extractions and one
broken match, and nothing else in the repository can see it.

An expected term counts as produced when the list covers it under the project's
own rule, not by string equality: extraction is measured the way the score reads
it, not the way it is spelled.

```bash
uv run python -m scripts.eval_extraction --runs 2
uv run python -m scripts.eval_extraction --only retail-shop --show
```

## Baseline, 2026-09-02 (prompts as rewritten for non-IT vocabulary, two runs)

| Metric | All 8 | Software | Everything else |
|---|---|---|---|
| recall | 0.857 | 1.000 | 0.830 |
| agreement | 0.783 | 1.000 | 0.737 |
| invented | 0 | 0 | 0 |

**Nothing was invented in any run** -- no perk, no employer name, no inferred
skill. The prompts refuse what they are told to refuse, including the two traps
that matter most: the resume of a care assistant never claims medication
administration, and a resume naming Docker never claims Kubernetes.

The gap is agreement, and it is entirely a non-IT gap. Two kinds of miss hide in
it, and telling them apart is what the dataset is for:

- **A real gap.** `stock counting` never comes out of the warehouse posting;
  `record keeping` comes out of neither side of the care home pair, though both
  texts describe keeping records; `invoice processing` appears on the posting
  side and not on the resume side, where SAP absorbs it.
- **A label worth arguing with.** The shop pair returns `till operation`,
  `cash handling` and `cash reconciliation` on *both* sides -- one vocabulary,
  perfectly matchable -- and the run is scored as a miss only because the label
  demands `customer service`. Arguably the model is right and the label is
  wrong. Read that case before trusting the 0.737.
