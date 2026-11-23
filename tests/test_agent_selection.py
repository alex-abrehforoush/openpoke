"""Which agents the interaction agent sees, and how each one is rendered."""

from zoneinfo import ZoneInfo

from server.agents.interaction_agent import agent as interaction_agent
from server.agents.interaction_agent.agent import _render_agent, _select_agents
from server.services.execution.roster import AgentRecord


def _agent(name, description="", day=None):
    last_active = f"2026-01-{day:02d}T09:00:00+00:00" if day else ""
    return AgentRecord(name=name, description=description, last_active_at=last_active)


def _names(agents):
    return [agent.name for agent in agents]


def _fillers(first_day, count):
    """Unrelated agents active on consecutive days, newest last."""
    return [_agent(f"Filler {d}", "Do routine work", d) for d in range(first_day, first_day + count)]


def test_without_a_match_only_the_five_most_recent_are_listed():
    agents = _fillers(1, 20)
    selected = _select_agents(agents, "yes, send it")
    assert _names(selected) == ["Filler 20", "Filler 19", "Filler 18", "Filler 17", "Filler 16"]


def test_older_agents_that_share_words_with_the_message_are_added():
    alice = _agent("Email to Alice", "Draft a lunch invite to Alice", day=1)
    selected = _select_agents([alice, *_fillers(2, 20)], "Did Alice reply about lunch?")
    assert alice in selected
    assert len(selected) == 6


def test_matches_rank_by_shared_words_then_recency():
    two_words = _agent("Lunch with Alice", day=1)
    one_word_older = _agent("Alice invoice", day=2)
    one_word_newer = _agent("Alice birthday", day=3)
    agents = [two_words, one_word_older, one_word_newer, *_fillers(10, 5)]

    selected = _select_agents(agents, "alice lunch")

    assert _names(selected[5:]) == ["Lunch with Alice", "Alice birthday", "Alice invoice"]


def test_stopwords_and_short_words_do_not_count_as_matches():
    old = _agent("Old agent", "Please do this for me with the team", day=1)
    selected = _select_agents([old, *_fillers(2, 5)], "please do it for me with the bank")
    assert old not in selected


def test_never_more_than_ten_even_when_everything_matches():
    agents = [_agent(f"Email agent {i}", "Reply to an email", day=1 + i % 28) for i in range(300)]
    assert len(_select_agents(agents, "check my email")) == 10


def test_render_shows_description_and_local_last_active_time(monkeypatch):
    monkeypatch.setattr(
        interaction_agent,
        "convert_to_user_timezone",
        lambda dt: dt.astimezone(ZoneInfo("America/Toronto")),
    )
    agent = AgentRecord(
        name='Email "Alice"',
        description="Reply <quickly> & politely",
        last_active_at="2026-01-15T17:30:00+00:00",
    )
    assert _render_agent(agent) == (
        '<agent name="Email &quot;Alice&quot;" last_active="2026-01-15 12:30">'
        "Reply &lt;quickly&gt; &amp; politely</agent>"
    )


def test_render_omits_last_active_when_unknown():
    assert _render_agent(AgentRecord(name="Legacy")) == '<agent name="Legacy"></agent>'
