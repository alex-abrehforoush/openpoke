"""An execution agent's system prompt keeps only its most recent requests."""

from types import SimpleNamespace

from server.agents.execution_agent import agent as execution_agent_module
from server.agents.execution_agent import runtime as runtime_module
from server.agents.execution_agent.runtime import ExecutionAgentRuntime
from server.services.execution.log_store import ExecutionAgentLogStore


def _system_prompt_after(past_requests, tmp_path, monkeypatch) -> str:
    logs = ExecutionAgentLogStore(tmp_path / "logs")
    for i in range(past_requests):
        logs.record_request("Gym Reminder", f"request {i:02d}")
        logs.record_agent_response("Gym Reminder", f"response {i:02d}")
    monkeypatch.setattr(execution_agent_module, "get_execution_agent_logs", lambda: logs)
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: SimpleNamespace(openrouter_api_key="test-key", execution_agent_model="test/model"),
    )
    return ExecutionAgentRuntime("Gym Reminder").agent.build_system_prompt_with_history()


def test_only_the_last_ten_requests_reach_the_prompt(tmp_path, monkeypatch):
    assert ExecutionAgentRuntime.HISTORY_REQUEST_LIMIT == 10
    prompt = _system_prompt_after(15, tmp_path, monkeypatch)

    assert "request 04" not in prompt and "response 04" not in prompt
    assert "request 05" in prompt  # oldest kept request
    assert "response 14" in prompt  # entries after the newest request are kept
    assert prompt.count("<agent_request") == 10


def test_short_histories_are_kept_whole(tmp_path, monkeypatch):
    prompt = _system_prompt_after(3, tmp_path, monkeypatch)
    assert prompt.count("<agent_request") == 3
    assert "request 00" in prompt
