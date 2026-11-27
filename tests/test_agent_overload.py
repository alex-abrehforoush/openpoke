"""OpenPoke's agent overload problem, end to end through prompt construction.

The interaction agent's prompt includes an <active_agents> block built from the
roster. The roster only ever grows; originally the block listed every agent in
it, so the prompt grew with every task the user had ever delegated.
"""

from server.agents.interaction_agent import agent as interaction_agent
from server.services.execution.roster import AgentRoster

MAX_LISTED = interaction_agent.RECENT_AGENT_SLOTS + interaction_agent.MATCHING_AGENT_SLOTS


def _use_roster(roster, monkeypatch):
    monkeypatch.setattr(interaction_agent, "get_agent_roster", lambda: roster)


def _rendered_agent_count(roster_path, total_agents, monkeypatch) -> int:
    roster = AgentRoster(roster_path)
    for i in range(total_agents):
        roster.touch(f"Task agent {i}", f"Do task number {i}")
    _use_roster(roster, monkeypatch)
    # "task" matches every agent, so this is the worst case for the cap.
    return interaction_agent._render_active_agents("Any update on that task?").count("<agent ")


def test_prompt_roster_does_not_grow_with_total_agents(tmp_path, monkeypatch):
    small = _rendered_agent_count(tmp_path / "small.json", 30, monkeypatch)
    large = _rendered_agent_count(tmp_path / "large.json", 300, monkeypatch)
    assert large == small == MAX_LISTED


def test_old_agent_is_listed_when_the_message_mentions_it(tmp_path, monkeypatch):
    roster = AgentRoster(tmp_path / "roster.json")
    roster.touch("Email to Alice", "Draft a lunch invite to Alice for Friday")
    for i in range(50):  # 50 newer, unrelated agents push it out of the recent slots
        roster.touch(f"Task agent {i}", f"Do task number {i}")
    _use_roster(roster, monkeypatch)

    def prompt_for(message: str) -> str:
        return interaction_agent.prepare_message_with_history(message, "")[0]["content"]

    assert 'name="Email to Alice"' in prompt_for("Did Alice reply about lunch?")
    assert 'name="Email to Alice"' not in prompt_for("Remind me to call mom")


def test_a_short_follow_up_does_not_hide_what_the_agent_is_for(tmp_path, monkeypatch):
    roster = AgentRoster(tmp_path / "roster.json")
    roster.touch("Email to Priya", "Email Priya to confirm the venue deposit")
    roster.touch("Email to Priya", "Send the email")  # follow-ups are often this short
    for i in range(50):
        roster.touch(f"Task agent {i}", f"Do task number {i}")
    _use_roster(roster, monkeypatch)

    block = interaction_agent._render_active_agents("Any update on the venue deposit?")
    assert 'name="Email to Priya"' in block
