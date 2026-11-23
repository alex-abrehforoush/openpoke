"""Reproduces OpenPoke's agent overload problem.

The interaction agent's prompt includes an <active_agents> block built from the
roster. The roster only ever grows, and the block lists every agent in it, so
the prompt grows with every task the user has ever delegated.
"""

import pytest

from server.agents.interaction_agent import agent as interaction_agent
from server.services.execution.roster import AgentRoster


def _rendered_agent_count(roster_path, total_agents, monkeypatch) -> int:
    roster = AgentRoster(roster_path)
    for i in range(total_agents):
        roster.add_agent(f"Task agent {i}")
    monkeypatch.setattr(interaction_agent, "get_agent_roster", lambda: roster)
    return interaction_agent._render_active_agents().count("<agent ")


@pytest.mark.xfail(
    strict=True,
    reason="Agent overload: the prompt lists every agent ever created",
)
def test_prompt_roster_does_not_grow_with_total_agents(tmp_path, monkeypatch):
    small = _rendered_agent_count(tmp_path / "small.json", 30, monkeypatch)
    large = _rendered_agent_count(tmp_path / "large.json", 300, monkeypatch)
    assert large == small
