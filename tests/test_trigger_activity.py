"""A scheduled run counts as agent activity, so a reply to a reminder finds its agent."""

import asyncio
from types import SimpleNamespace

from server.agents.execution_agent.runtime import ExecutionResult
from server.services import trigger_scheduler as scheduler_module
from server.services.execution import roster as roster_module
from server.services.execution.roster import AgentRoster
from server.services.triggers.models import TriggerRecord


def test_a_scheduled_run_counts_as_agent_activity(tmp_path, monkeypatch):
    times = iter(["2026-03-02T12:00:00.000000+00:00", "2026-11-16T12:00:00.000000+00:00"])
    monkeypatch.setattr(roster_module, "_utc_now_iso", lambda: next(times))
    roster = AgentRoster(tmp_path / "roster.json")
    roster.touch("Gym Reminder", "Remind the user to go to the gym every Monday at 7am")
    executed = []

    class FakeBatchManager:
        async def execute_agent(self, agent_name, instructions):
            executed.append(agent_name)
            return ExecutionResult(agent_name=agent_name, success=True, response="Reminder sent")

    monkeypatch.setattr(scheduler_module, "get_agent_roster", lambda: roster)
    monkeypatch.setattr(scheduler_module, "ExecutionBatchManager", FakeBatchManager)
    scheduler = scheduler_module.TriggerScheduler()
    # Keep the real trigger store untouched.
    scheduler._service = SimpleNamespace(schedule_next_occurrence=lambda *args, **kwargs: None)
    trigger = TriggerRecord(
        id=1,
        agent_name="Gym Reminder",
        payload="Time for the gym!",
        status="active",
        created_at="2026-03-02T12:00:00Z",
        updated_at="2026-03-02T12:00:00Z",
    )

    asyncio.run(scheduler._execute_trigger(trigger))

    record = roster.find("Gym Reminder")
    assert executed == ["Gym Reminder"]
    assert record.last_active_at == "2026-11-16T12:00:00.000000+00:00"
    assert record.description == "Remind the user to go to the gym every Monday at 7am"
