"""What the interaction agent's model is shown, before ("baseline") and after ("fixed") the fix.

Both variants go through the real prepare_message_with_history; only the
<active_agents> block differs. The fixed block comes from the real
_render_active_agents, run on an in-memory roster instead of roster.json.
"""

from datetime import timezone
from html import escape
from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch

from server.agents.interaction_agent import agent as interaction_agent
from server.services.execution.log_store import _slugify
from server.services.execution.roster import AgentRecord

VARIANTS = ("baseline", "fixed")
UPSTREAM_COMMIT = "5b5f635"  # shlokkhemani/openpoke main, before the fix


def baseline_roster_block(agents: list[AgentRecord]) -> str:
    """Upstream _render_active_agents: every agent's name, nothing else."""
    if not agents:
        return "None"

    rendered = []
    for agent in agents:
        name = escape(agent.name or "agent", quote=True)
        rendered.append(f'<agent name="{name}" />')

    return "\n".join(rendered)


def fixed_roster_block(agents: list[AgentRecord], latest_text: str) -> str:
    """The fixed _render_active_agents, run on `agents`."""
    roster = SimpleNamespace(load=lambda: None, get_agents=lambda: list(agents))
    # The user's timezone lives in server/data; pin UTC so output is the same on every machine.
    with patch.object(interaction_agent, "get_agent_roster", return_value=roster), patch.object(
        interaction_agent, "convert_to_user_timezone", lambda dt: dt.astimezone(timezone.utc)
    ):
        return interaction_agent._render_active_agents(latest_text)


def roster_block(variant: str, agents: list[AgentRecord], latest_text: str) -> str:
    if variant == "baseline":
        return baseline_roster_block(agents)
    return fixed_roster_block(agents, latest_text)


def interaction_message(variant: str, agents: list[AgentRecord], history: str, latest_text: str) -> str:
    """The user message the interaction agent's model receives for this turn."""
    block = roster_block(variant, agents, latest_text)
    with patch.object(interaction_agent, "_render_active_agents", lambda _text: block):
        return interaction_agent.prepare_message_with_history(latest_text, history)[0]["content"]


def resolve_agent(variant: str, name: str, agents: list[AgentRecord]) -> Optional[AgentRecord]:
    """The existing agent that a send to `name` reuses; None means a new agent is created.

    Upstream reused an agent only on an exact name match. The fix compares
    slugs, as AgentRoster.find does.
    """
    if variant == "baseline":
        return next((agent for agent in agents if agent.name == name), None)
    key = _slugify(name)
    return next((agent for agent in agents if _slugify(agent.name) == key), None)
