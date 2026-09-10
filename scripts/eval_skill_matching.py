"""Measure the skill-matching rule against the hand-labelled cases (W-1)."""

import asyncio
import json
import pathlib
import sys
from typing import Any

from app.core.config import get_settings
from app.core.prompts import StaticPromptStore
from app.services.judging import AnthropicRequirementJudge, RequirementJudge, settle
from app.services.matching import cover, evidence

DATASET = pathlib.Path("evals/skill_matching.json")


def rate(hits: int, total: int) -> float:
    """Return a share, calling the empty case perfect rather than undefined."""
    return 1.0 if total == 0 else hits / total


async def predict(case: dict[str, Any], judge: RequirementJudge | None) -> set[str]:
    """Return the requirements this case is judged to meet."""
    requirements: list[str] = case["requirements"]
    matched, _ = cover(requirements, evidence(case["resume"], case["skills"]))

    if judge is None:
        return set(matched)

    verdicts = await judge.judge(requirements, case["resume"], case["skills"])
    matched, _, _ = settle(requirements, matched, verdicts)

    return set(matched)


def report(case: dict[str, Any], predicted: set[str]) -> tuple[int, int, int, float]:
    """Print one case and return its true positives, false ones and the gap."""
    requirements: list[str] = case["requirements"]
    expected = set(case["expected_met"])

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
    """Print the four numbers a matcher is compared on, for one group."""
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


async def main() -> int:
    """Run every case and print the aggregate the next change is compared to."""
    if not DATASET.exists():
        print(f"No dataset at {DATASET}")

        return 1

    cases: list[dict[str, Any]] = json.loads(DATASET.read_text(encoding="utf-8"))[
        "cases"
    ]
    judge: RequirementJudge | None = None

    if "--judge" in sys.argv:
        if get_settings().anthropic_api_key is None:
            print("ANTHROPIC_API_KEY is not configured: --judge calls a model.")

            return 1

        judge = AnthropicRequirementJudge(get_settings(), StaticPromptStore())

    tallies: dict[str, list[tuple[int, int, int, float]]] = {}

    for case in cases:
        scored = report(case, await predict(case, judge))
        tallies.setdefault(case["domain"], []).append(scored)

    print()
    summarise("all", [row for group in tallies.values() for row in group])

    for domain in sorted(tallies):
        print()
        summarise(domain, tallies[domain])

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
