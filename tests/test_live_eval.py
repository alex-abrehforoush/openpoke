"""The live evaluator's zero-spend checks and scoring (evals/live_eval.py), with no network."""

import json

import pytest

from evals.dataset import CASES, build_roster
from evals.live_eval import (
    RefusedToSpend,
    build_request,
    cache_key,
    calls_to_send,
    check_free_quota,
    check_model_is_free,
    check_response_cost,
    chosen_agent,
    outcome,
)

FREE = "google/gemma-4-31b-it:free"


def _models(pricing, model_id=FREE):
    """The shape of GET /api/v1/models."""
    return {"data": [{"id": model_id, "pricing": pricing}]}


def test_free_model_listed_at_zero_passes():
    check_model_is_free(FREE, _models({"prompt": "0", "completion": "0"}))


@pytest.mark.parametrize(
    "model, models_payload",
    [
        ("google/gemma-4-31b-it", _models({"prompt": "0", "completion": "0"}, "google/gemma-4-31b-it")),  # no :free
        (FREE, _models({"prompt": "0", "completion": "0.000001"})),  # a price above 0
        (FREE, _models({"prompt": "0", "completion": "0", "request": "0.01"})),  # any listed price counts
        (FREE, _models({"prompt": "-1", "completion": "-1"})),  # variable pricing
        (FREE, _models({"prompt": "0"})),  # completion price missing
        (FREE, {"data": []}),  # model not listed
    ],
)
def test_paid_or_unknown_pricing_is_refused(model, models_payload):
    with pytest.raises(RefusedToSpend):
        check_model_is_free(model, models_payload)


def test_free_quota_must_cover_the_run():
    key = {"data": {"usage": 0, "free_model_daily_requests": {"used": 12, "limit": 50, "remaining": 38}}}
    assert check_free_quota(key, 38) == 0.0
    with pytest.raises(RefusedToSpend):
        check_free_quota(key, 40)
    with pytest.raises(RefusedToSpend):
        check_free_quota({"data": {"usage": 0}}, 1)  # quota not reported


def test_a_response_that_cost_anything_stops_the_run():
    check_response_cost({"usage": {"cost": 0}})
    with pytest.raises(RefusedToSpend):
        check_response_cost({"usage": {"cost": 0.0001}})


def test_requests_are_free_deterministic_and_must_route_to_an_agent():
    agents = build_roster(25)
    prompts = {"baseline": "old prompt", "fixed": "new prompt"}
    request = build_request(FREE, "fixed", CASES[0], agents, prompts)
    assert request["model"] == FREE and request["temperature"] == 0
    assert request["tool_choice"]["function"]["name"] == "send_message_to_agent"
    with pytest.raises(RefusedToSpend):
        build_request("anthropic/claude-sonnet-4", "fixed", CASES[0], agents, prompts)


def test_cached_requests_are_not_resent_and_the_call_cap_holds():
    requests = [{"n": i} for i in range(50)]
    cache = {cache_key(request): {} for request in requests[:10]}
    assert calls_to_send(requests, cache) == requests[10:]
    with pytest.raises(RefusedToSpend):
        calls_to_send(requests, {})  # 50 calls is over the cap of 45


def _routed_to(agent_name):
    arguments = json.dumps({"agent_name": agent_name, "instructions": "..."})
    call = {"function": {"name": "send_message_to_agent", "arguments": arguments}}
    return {"choices": [{"message": {"tool_calls": [call]}}]}


def test_outcomes():
    agents = build_roster(25)
    callback = next(case for case in CASES if case.id == "keyword-tax")  # expects "Tax Documents"
    new_task = next(case for case in CASES if case.kind == "new")

    assert outcome("fixed", callback, chosen_agent(_routed_to("Tax Documents")), agents) == "correct"
    assert outcome("fixed", callback, "tax documents", agents) == "correct"  # same slug
    assert outcome("baseline", callback, "tax documents", agents) == "duplicate"  # upstream needed the exact name
    assert outcome("fixed", callback, "Tax Return Help", agents) == "duplicate"
    assert outcome("fixed", callback, "Gym Reminder", agents) == "wrong agent"
    assert outcome("fixed", new_task, "Restaurant Finder", agents) == "correct"
    assert outcome("fixed", new_task, "Gym Reminder", agents) == "wrong agent"
    assert chosen_agent({"choices": [{"message": {"content": "Sure!"}}]}) is None
    assert outcome("fixed", callback, None, agents) == "no call"
