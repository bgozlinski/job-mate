"""Measure the skill-matching rule against the hand-labelled cases (W-1).

Not a test: nothing here passes or fails. It prints the numbers a change to
the matching rule has to be argued with, so that "the model matches better"
can be told apart from "the model matches more" -- two different things, and
only one of them is an improvement.

Recall is the interesting half. Precision is easy: awarding nothing scores
perfectly on it, and awarding everything scores perfectly on recall. What a
matcher is for is both at once.

    uv run python -m scripts.eval_skill_matching
"""

import json
import pathlib
import sys
from typing import Any

from app.services.matching import cover, evidence

DATASET = pathlib.Path("evals/skill_matching.json")


def rate(hits: int, total: int) -> float:
    """Return a share, calling the empty case perfect rather than undefined."""
    return 1.0 if total == 0 else hits / total


def report(case: dict[str, Any]) -> tuple[int, int, int, float]:
    """Print one case and return its true positives, false ones and the gap.

    The gap is between the score the rule computes and the score the labels
    imply -- the number the user is actually shown, which is why it is worth
    reporting next to the set arithmetic.
    """
    requirements: list[str] = case["requirements"]
    expected = set(case["expected_met"])
    matched, _ = cover(requirements, evidence(case["resume"], case["skills"]))
    predicted = set(matched)

    hit = predicted & expected
    wrong = predicted - expected
    missed = expected - predicted
    scored = rate(len(predicted), len(requirements))
    labelled = rate(len(expected), len(requirements))
    verdict = "ok" if not wrong and not missed else "  "

    print(f"{verdict} {case['id']:<34} score {scored:.2f} vs {labelled:.2f}")

    for requirement in sorted(missed):
        print(f"     missed:  {requirement}")

    for requirement in sorted(wrong):
        print(f"     awarded: {requirement}  (the labels say no)")

    return len(hit), len(wrong), len(missed), abs(scored - labelled)


def summarise(name: str, tally: list[tuple[int, int, int, float]]) -> None:
    """Print the four numbers a matcher is compared on, for one group.

    Split by domain, because that is where a rule tuned on one vocabulary
    hides its failures: software terms are what this code was written
    against, and a kitchen or a garage names the same work differently.
    """
    hits = sum(row[0] for row in tally)
    wrong = sum(row[1] for row in tally)
    missed = sum(row[2] for row in tally)
    precision = rate(hits, hits + wrong)
    recall = rate(hits, hits + missed)
    total = precision + recall
    f1 = 0.0 if total == 0 else 2 * precision * recall / total

    print(
        f"{name:<10} cases {len(tally):>3}   met {hits:>3}   awarded wrongly {wrong:>2}"
        f"   missed {missed:>2}"
    )
    print(
        f"{'':<10} precision {precision:.3f}   recall {recall:.3f}   f1 {f1:.3f}"
        f"   mean score gap {sum(row[3] for row in tally) / len(tally):.3f}"
    )


def main() -> int:
    """Run every case and print the aggregate the next change is compared to."""
    if not DATASET.exists():
        print(f"No dataset at {DATASET}")

        return 1

    cases: list[dict[str, Any]] = json.loads(DATASET.read_text(encoding="utf-8"))[
        "cases"
    ]
    tallies: dict[str, list[tuple[int, int, int, float]]] = {}

    for case in cases:
        tallies.setdefault(case["domain"], []).append(report(case))

    print()
    summarise("all", [row for group in tallies.values() for row in group])

    for domain in sorted(tallies):
        print()
        summarise(domain, tallies[domain])

    return 0


if __name__ == "__main__":
    sys.exit(main())
