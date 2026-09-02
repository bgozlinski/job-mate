"""Measure what the extraction prompts read out of a posting and a resume.

The other evaluation is arithmetic over fixed lists; this one calls a real
model. It therefore costs money, needs ANTHROPIC_API_KEY and answers a little
differently every time -- which is the reason for --runs: a term that appears
in one run out of three is not extracted, it is guessed, and a prompt change
that fixes a case only sometimes has not fixed it.

Three things are measured, and the third is the one nothing else covers:

- recall of what must be there, per side and per domain;
- violations, meaning something the posting offers or the resume never claimed;
- agreement, meaning a term that both sides produce in a form cover() links.
  A posting saying "postgresql" and a resume saying "postgres" are two correct
  extractions and one broken match, and only this number sees it.

An expected term counts as produced when the list covers it under the
project's own rule, not by string equality: extraction is measured the way the
score will read it.

    uv run python -m scripts.eval_extraction
    uv run python -m scripts.eval_extraction --runs 3
    uv run python -m scripts.eval_extraction --only retail-shop --show

Traces land in Langfuse like any other extraction. From the host that means
LANGFUSE_HOST=http://localhost:3000; LANGFUSE_TRACING_ENABLED=false turns them
off entirely.
"""

import asyncio
import json
import pathlib
import sys
from typing import Any

from app.core.config import get_settings
from app.core.prompts import (
    JOB_POST_SKILLS,
    RESUME_SKILLS,
    StaticPromptStore,
)
from app.services.matching import cover, evidence, tokenize
from app.services.requirements import AnthropicSkillExtractor

DATASET = pathlib.Path("evals/extraction.json")


def produced(terms: list[str], expected: list[str]) -> list[str]:
    """Return the expected terms the produced list answers."""
    matched, _ = cover(expected, evidence(" ".join(terms), None))

    return matched


def violated(terms: list[str], forbidden: list[str]) -> list[str]:
    """Return the forbidden terms an entry carries, in either direction.

    Either direction, because both failures are the same mistake seen from
    two sides: an entry "private healthcare" against a forbidden "healthcare",
    and an entry "healthcare" against a forbidden "private healthcare".
    """
    hits = []

    for term in forbidden:
        wanted = set(tokenize(term))

        for entry in terms:
            words = set(tokenize(entry))

            if words and (wanted <= words or words <= wanted):
                hits.append(term)

                break

    return hits


async def read(text: str, prompt: str) -> list[str]:
    """Run one extraction with the shipped text of the given prompt."""
    extractor = AnthropicSkillExtractor(get_settings(), StaticPromptStore(), prompt)

    return await extractor.extract(text)


async def evaluate(pair: dict[str, Any], runs: int) -> dict[str, Any]:
    """Run both sides of one pair, `runs` times, and score every run."""
    result: dict[str, Any] = {"id": pair["id"], "domain": pair["domain"], "runs": []}

    for _ in range(runs):
        posting = await read(pair["posting"]["text"], JOB_POST_SKILLS)
        resume = await read(pair["resume"]["text"], RESUME_SKILLS)
        agreed = produced(posting, pair["must_agree"])
        both = [term for term in agreed if term in produced(resume, pair["must_agree"])]

        result["runs"].append(
            {
                "posting": posting,
                "resume": resume,
                "posting_found": produced(posting, pair["posting"]["must_include"]),
                "resume_found": produced(resume, pair["resume"]["must_include"]),
                "posting_violations": violated(
                    posting, pair["posting"]["must_exclude"]
                ),
                "resume_violations": violated(resume, pair["resume"]["must_exclude"]),
                "agreed": both,
            }
        )

    return result


def share(found: int, wanted: int) -> float:
    """Return a share, calling the empty case perfect rather than undefined."""
    return 1.0 if wanted == 0 else found / wanted


def report(pair: dict[str, Any], scored: dict[str, Any], show: bool = False) -> None:
    """Print one pair: what was missed, what was invented, what disagreed.

    With show, the lists themselves as well -- a miss is only actionable once
    you can read the words the model chose instead.
    """
    print(f"\n{scored['id']} ({scored['domain']})")

    for index, run in enumerate(scored["runs"], start=1):
        missing = {
            "posting": set(pair["posting"]["must_include"]) - set(run["posting_found"]),
            "resume": set(pair["resume"]["must_include"]) - set(run["resume_found"]),
        }
        disagreed = set(pair["must_agree"]) - set(run["agreed"])
        clean = not any(missing.values()) and not disagreed
        clean = clean and not run["posting_violations"] and not run["resume_violations"]

        print(f"  run {index} {'ok' if clean else '  '}")

        for side in ("posting", "resume"):
            for term in sorted(missing[side]):
                print(f"    {side} missed:    {term}")

            for term in sorted(run[f"{side}_violations"]):
                print(f"    {side} invented:  {term}")

        for term in sorted(disagreed):
            print(f"    disagreed:         {term}")

        if show:
            print(f"    posting list: {run['posting']}")
            print(f"    resume list:  {run['resume']}")


def summarise(name: str, pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    """Print recall, violations and agreement for one group of pairs."""
    found = wanted = agreed = agreeable = violations = 0

    for pair, scored in pairs:
        for run in scored["runs"]:
            found += len(run["posting_found"]) + len(run["resume_found"])
            wanted += len(pair["posting"]["must_include"])
            wanted += len(pair["resume"]["must_include"])
            agreed += len(run["agreed"])
            agreeable += len(pair["must_agree"])
            violations += len(run["posting_violations"])
            violations += len(run["resume_violations"])

    print(
        f"{name:<10} pairs {len(pairs):>3}   recall {share(found, wanted):.3f}"
        f"   agreement {share(agreed, agreeable):.3f}   invented {violations:>3}"
    )


async def main() -> int:
    """Run every pair and print the aggregate a prompt change is compared to."""
    runs = 1

    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])

    if get_settings().anthropic_api_key is None:
        print("ANTHROPIC_API_KEY is not configured: this evaluation calls a model.")

        return 1

    pairs: list[dict[str, Any]] = json.loads(DATASET.read_text(encoding="utf-8"))[
        "pairs"
    ]

    if "--only" in sys.argv:
        wanted = sys.argv[sys.argv.index("--only") + 1]
        pairs = [pair for pair in pairs if pair["id"] == wanted]

    show = "--show" in sys.argv
    scored = []

    for pair in pairs:
        result = await evaluate(pair, runs)
        report(pair, result, show)
        scored.append((pair, result))

    print()
    summarise("all", scored)

    for domain in sorted({pair["domain"] for pair in pairs}):
        summarise(domain, [row for row in scored if row[0]["domain"] == domain])

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
