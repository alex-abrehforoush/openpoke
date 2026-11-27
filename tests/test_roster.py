"""The roster keeps one record per agent and treats near-duplicate names as one agent."""

import asyncio
import json
from types import SimpleNamespace

from server.agents.interaction_agent import tools as interaction_tools
from server.services.execution import roster as roster_module
from server.services.execution.log_store import ExecutionAgentLogStore
from server.services.execution.roster import DESCRIPTION_MAX_CHARS, AgentRoster


def test_touch_creates_a_record_that_survives_reload(tmp_path):
    path = tmp_path / "roster.json"
    AgentRoster(path).touch("Email to Alice", "Draft a lunch invite to Alice for Friday")

    record = AgentRoster(path).find("Email to Alice")  # a fresh instance reads the file
    assert record.description == "Draft a lunch invite to Alice for Friday"
    assert record.created_at and record.last_active_at


def test_touch_refreshes_the_time_and_keeps_the_first_description(tmp_path, monkeypatch):
    times = iter(["2026-01-01T09:00:00+00:00", "2026-01-02T09:00:00+00:00"])
    monkeypatch.setattr(roster_module, "_utc_now_iso", lambda: next(times))
    roster = AgentRoster(tmp_path / "roster.json")

    roster.touch("Email to Alice", "Draft a lunch invite")
    record = roster.touch("Email to Alice", "Move the lunch to Saturday")

    assert len(roster.get_agents()) == 1
    assert record.created_at == "2026-01-01T09:00:00+00:00"
    assert record.last_active_at == "2026-01-02T09:00:00+00:00"
    assert record.description == "Draft a lunch invite"  # what the agent was created for


def test_an_agent_from_the_names_only_roster_gets_a_description(tmp_path):
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(["Gym Reminder"]))

    record = AgentRoster(path).touch("Gym Reminder", "Remind the user to go to the gym at 7am")

    assert record.description == "Remind the user to go to the gym at 7am"


def test_description_is_flattened_and_capped(tmp_path):
    record = AgentRoster(tmp_path / "roster.json").touch(
        "Agent", "line one\n\n   line two " + "x" * 500
    )
    assert record.description.startswith("line one line two x")
    assert len(record.description) == DESCRIPTION_MAX_CHARS


def test_names_differing_only_in_case_or_punctuation_are_one_agent(tmp_path):
    roster = AgentRoster(tmp_path / "roster.json")
    roster.touch("Email to Alice", "Draft a lunch invite")

    record = roster.touch("email to alice!", "Move the lunch to Saturday")

    assert record.name == "Email to Alice"
    assert len(roster.get_agents()) == 1


def test_loads_the_original_list_of_names_format(tmp_path):
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(["Email to Alice", "Gym Reminder"]))

    roster = AgentRoster(path)

    assert [r.name for r in roster.get_agents()] == ["Email to Alice", "Gym Reminder"]
    assert roster.find("Gym Reminder").last_active_at == ""


def test_send_message_to_agent_runs_a_near_duplicate_under_the_existing_name(
    tmp_path, monkeypatch
):
    roster = AgentRoster(tmp_path / "roster.json")
    roster.touch("Email to Alice", "Draft a lunch invite")
    executed = []

    async def fake_execute_agent(agent_name, instructions):
        executed.append(agent_name)
        return SimpleNamespace(success=True)

    monkeypatch.setattr(interaction_tools, "get_agent_roster", lambda: roster)
    monkeypatch.setattr(
        interaction_tools,
        "get_execution_agent_logs",
        lambda: ExecutionAgentLogStore(tmp_path / "logs"),
    )
    monkeypatch.setattr(
        interaction_tools._EXECUTION_BATCH_MANAGER, "execute_agent", fake_execute_agent
    )

    async def send():
        result = interaction_tools.send_message_to_agent("email to alice", "Make it Saturday")
        await asyncio.sleep(0)  # let the background execution task run
        return result

    result = asyncio.run(send())

    assert result.payload == {
        "status": "submitted",
        "agent_name": "Email to Alice",
        "new_agent_created": False,
    }
    assert executed == ["Email to Alice"]
