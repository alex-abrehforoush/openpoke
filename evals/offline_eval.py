"""Offline evaluator: what the interaction agent is shown, before vs after the fix.

No model calls and no network; deterministic and fast.
Run: python -m evals.offline_eval
"""

import re
from html import unescape
from pathlib import Path

from .dataset import CASES, NAME_VARIANTS, build_roster
from .harness import VARIANTS, resolve_agent, roster_block

ROSTER_SIZES = (25, 100, 300)
CALLBACK_KINDS = ("recent", "keyword", "paraphrase")  # cases whose answer is an existing agent
CHARS_PER_TOKEN = 4  # rough average for English text
REPORT_PATH = Path(__file__).parent / "results" / "offline_results.md"


def listed_names(block: str) -> list[str]:
    return [unescape(name) for name in re.findall(r'<agent name="([^"]*)"', block)]


def evaluate(size: int, variant: str) -> dict:
    """Prompt size and recall of the right agent over all cases, for one roster size."""
    agents = build_roster(size)
    listed_counts, block_chars = [], []
    found = {kind: 0 for kind in CALLBACK_KINDS}
    total = {kind: 0 for kind in CALLBACK_KINDS}

    for case in CASES:
        block = roster_block(variant, agents, case.message)
        names = listed_names(block)
        listed_counts.append(len(names))
        block_chars.append(len(block))
        if case.expected_agent is not None:
            total[case.kind] += 1
            found[case.kind] += case.expected_agent in names

    return {
        "max_listed": max(listed_counts),
        "mean_listed": sum(listed_counts) / len(CASES),
        "mean_tokens": sum(block_chars) / len(CASES) / CHARS_PER_TOKEN,
        "found": found,
        "total": total,
    }


def near_duplicate_reuse(variant: str) -> tuple[int, int]:
    """How many alternative spellings of an existing agent's name reuse that agent."""
    agents = build_roster(25)
    reused = 0
    for spelling, original in NAME_VARIANTS:
        match = resolve_agent(variant, spelling, agents)
        reused += match is not None and match.name == original
    return reused, len(NAME_VARIANTS)


def report() -> str:
    lines = [
        "| Agents in roster | Version | Agents listed per turn (mean / max) | Roster block, ~tokens | "
        "Recent follow-up | Keyword callback | Paraphrase callback |",
        "|---|---|---|---|---|---|---|",
    ]
    for size in ROSTER_SIZES:
        for variant in VARIANTS:
            r = evaluate(size, variant)
            recall = [f"{r['found'][kind]}/{r['total'][kind]}" for kind in CALLBACK_KINDS]
            lines.append(
                f"| {size} | {variant} | {r['mean_listed']:.1f} / {r['max_listed']} | "
                f"{r['mean_tokens']:,.0f} | " + " | ".join(recall) + " |"
            )

    lines.append("")
    for variant in VARIANTS:
        reused, total = near_duplicate_reuse(variant)
        lines.append(f"- Near-duplicate names that reuse the existing agent, {variant}: {reused}/{total}")
    return "\n".join(lines)


def main() -> None:
    text = report()
    print(text)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
