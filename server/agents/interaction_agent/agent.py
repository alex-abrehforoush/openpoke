"""Interaction agent helpers for prompt construction."""

import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Dict, List

from ...services.execution import get_agent_roster
from ...services.execution.roster import AgentRecord
from ...utils.timezones import convert_to_user_timezone

_prompt_path = Path(__file__).parent / "system_prompt.md"
SYSTEM_PROMPT = _prompt_path.read_text(encoding="utf-8").strip()

# The prompt lists at most RECENT + MATCHING agents, however many exist.
# Agents left out keep their history and are reused when addressed by name.
RECENT_AGENT_SLOTS = 5  # follow-ups ("send it") usually go to a recent agent
MATCHING_AGENT_SLOTS = 5  # older agents whose name/description match the message

# Common words that would make almost every agent look relevant.
_STOPWORDS = frozenset(
    "about and are can for from has have her his how its not our please she "
    "that the them they this was what when who will with you your".split()
)


# Load and return the pre-defined system prompt from markdown file
def build_system_prompt() -> str:
    """Return the static system prompt for the interaction agent."""
    return SYSTEM_PROMPT


# Build structured message with conversation history, active agents, and current turn
def prepare_message_with_history(
    latest_text: str,
    transcript: str,
    message_type: str = "user",
) -> List[Dict[str, str]]:
    """Compose a message that bundles history, roster, and the latest turn."""
    sections: List[str] = []

    sections.append(_render_conversation_history(transcript))
    sections.append(f"<active_agents>\n{_render_active_agents(latest_text)}\n</active_agents>")
    sections.append(_render_current_turn(latest_text, message_type))

    content = "\n\n".join(sections)
    return [{"role": "user", "content": content}]


# Format conversation transcript into XML tags for LLM context
def _render_conversation_history(transcript: str) -> str:
    history = transcript.strip()
    if not history:
        history = "None"
    return f"<conversation_history>\n{history}\n</conversation_history>"


# Format the execution agents relevant to this turn into XML tags for the LLM
def _render_active_agents(latest_text: str) -> str:
    roster = get_agent_roster()
    roster.load()
    agents = _select_agents(roster.get_agents(), latest_text)

    if not agents:
        return "None"

    return "\n".join(_render_agent(agent) for agent in agents)


def _keywords(text: str) -> set[str]:
    """Lowercase words of 3+ characters, minus stopwords."""
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) >= 3 and word not in _STOPWORDS
    }


def _select_agents(agents: List[AgentRecord], latest_text: str) -> List[AgentRecord]:
    """Most recently active agents, then older agents that match the message."""
    by_recency = sorted(agents, key=lambda agent: agent.last_active_at, reverse=True)
    recent = by_recency[:RECENT_AGENT_SLOTS]

    message_words = _keywords(latest_text)
    scored = [
        (len(message_words & _keywords(f"{agent.name} {agent.description}")), agent)
        for agent in by_recency[RECENT_AGENT_SLOTS:]
    ]
    # The sort is stable, so agents with equal scores stay in recency order.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    matching = [agent for score, agent in scored if score > 0]

    return recent + matching[:MATCHING_AGENT_SLOTS]


def _render_agent(agent: AgentRecord) -> str:
    name = escape(agent.name or "agent", quote=True)
    description = escape(agent.description, quote=False)
    last_active = ""
    if agent.last_active_at:
        try:
            local = convert_to_user_timezone(datetime.fromisoformat(agent.last_active_at))
            last_active = f' last_active="{local:%Y-%m-%d %H:%M}"'
        except ValueError:  # hand-edited roster.json; show the agent without it
            pass
    return f'<agent name="{name}"{last_active}>{description}</agent>'


# Wrap the current message in appropriate XML tags based on sender type
def _render_current_turn(latest_text: str, message_type: str) -> str:
    tag = "new_agent_message" if message_type == "agent" else "new_user_message"
    body = latest_text.strip()
    return f"<{tag}>\n{body}\n</{tag}>"
