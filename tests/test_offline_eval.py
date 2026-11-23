"""Regression guard on the offline evaluator (evals/offline_eval.py), and a check that it measures the real prompt."""

import json
from dataclasses import asdict
from datetime import timezone

from evals.dataset import CASES, build_roster
from evals.harness import interaction_message
from evals.offline_eval import ROSTER_SIZES, evaluate, near_duplicate_reuse
from server.agents.interaction_agent import agent as interaction_agent
from server.services.execution.roster import AgentRoster


def test_fixed_prompt_stays_bounded_and_finds_recent_and_keyword_callbacks():
    limit = interaction_agent.RECENT_AGENT_SLOTS + interaction_agent.MATCHING_AGENT_SLOTS
    for size in ROSTER_SIZES:
        result = evaluate(size, "fixed")
        assert result["max_listed"] <= limit
        for kind in ("recent", "keyword"):
            assert result["found"][kind] == result["total"][kind], (size, kind)


def test_baseline_lists_every_agent():
    # The evaluator reproduces the overload: before the fix, all 300 agents are listed.
    assert evaluate(300, "baseline")["max_listed"] == 300


def test_near_duplicate_names_reuse_the_existing_agent():
    assert near_duplicate_reuse("baseline") == (0, 10)
    assert near_duplicate_reuse("fixed") == (7, 10)  # the 3 misses differ in words, not spelling


def test_harness_builds_the_same_message_as_the_server(tmp_path, monkeypatch):
    agents = build_roster(100)
    roster_path = tmp_path / "roster.json"
    roster_path.write_text(json.dumps([asdict(agent) for agent in agents]))
    roster = AgentRoster(roster_path)
    monkeypatch.setattr(interaction_agent, "get_agent_roster", lambda: roster)
    monkeypatch.setattr(interaction_agent, "convert_to_user_timezone", lambda dt: dt.astimezone(timezone.utc))

    for case in CASES:
        server_message = interaction_agent.prepare_message_with_history(case.message, case.history)
        assert interaction_message("fixed", agents, case.history, case.message) == server_message[0]["content"]
