"""Live evaluator: does the model send each case to the right agent, before vs after the fix?

Opt-in and free only. It refuses to send anything unless the model id ends in
":free", OpenRouter lists the model at $0, and today's free-request quota
covers the run. It stops on the first response that cost anything.

Each case is one call: the interaction agent's real request (system prompt,
history, <active_agents>, message) with the model required to call
send_message_to_agent, at temperature 0. The agent_name it picks is scored by
exact rules, no LLM judge. Responses are cached, so a re-run sends nothing new.

Run: python -m evals.live_eval [--model MODEL]   (needs OPENROUTER_API_KEY in .env)
"""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

from server.agents.interaction_agent.agent import build_system_prompt
from server.agents.interaction_agent.tools import get_tool_schemas
from server.config import get_settings
from server.services.execution.roster import AgentRecord

from .dataset import CASES, Case, build_roster
from .harness import UPSTREAM_COMMIT, VARIANTS, interaction_message, resolve_agent

DEFAULT_MODEL = "google/gemma-4-31b-it:free"
ROSTER_SIZE = 300
MAX_CALLS = 45  # hard cap per run; the free tier allows 50 requests a day
SECONDS_BETWEEN_CALLS = 3.5  # the free tier allows 20 requests a minute
API_URL = "https://openrouter.ai/api/v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(__file__).parent / "results"
CACHE_PATH = RESULTS_DIR / "live_cache.json"
REPORT_PATH = RESULTS_DIR / "live_results.md"


class RefusedToSpend(RuntimeError):
    """A zero-spend check failed, so nothing (more) is sent."""


# ---------------------------------------------------------------- zero-spend checks

def _is_zero(value: object) -> bool:
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return False


def check_model_is_free(model: str, models_payload: dict) -> None:
    """The model id ends in ':free' and every price OpenRouter lists for it is 0."""
    if not model.endswith(":free"):
        raise RefusedToSpend(f"{model} is not a ':free' model")
    entry = next((m for m in models_payload.get("data", []) if m.get("id") == model), None)
    if entry is None:
        raise RefusedToSpend(f"{model} is not in OpenRouter's model list")
    pricing = entry.get("pricing") or {}
    if not {"prompt", "completion"} <= pricing.keys() or not all(map(_is_zero, pricing.values())):
        raise RefusedToSpend(f"{model} is not priced at $0: {pricing}")


def check_free_quota(key_payload: dict, calls_needed: int) -> float:
    """Refuse unless today's free requests cover the run; return the key's total spend so far."""
    data = key_payload.get("data") or {}
    remaining = (data.get("free_model_daily_requests") or {}).get("remaining")
    if not isinstance(remaining, int) or remaining < calls_needed:
        raise RefusedToSpend(f"need {calls_needed} free requests today; OpenRouter reports {remaining} left")
    spend = data.get("usage")
    if not isinstance(spend, (int, float)):
        raise RefusedToSpend(f"OpenRouter did not report the key's spend: {spend!r}")
    return float(spend)


def check_response_cost(response: dict) -> None:
    cost = (response.get("usage") or {}).get("cost", 0)
    if not _is_zero(cost):
        raise RefusedToSpend(f"a response cost ${cost}; stopping")


def calls_to_send(requests: list[dict], cache: dict) -> list[dict]:
    pending = [request for request in requests if cache_key(request) not in cache]
    if len(pending) > MAX_CALLS:
        raise RefusedToSpend(f"{len(pending)} calls planned; the cap is {MAX_CALLS}")
    return pending


# ---------------------------------------------------------------- requests

def system_prompts() -> dict[str, str]:
    """The interaction agent's system prompt before (from git) and after the fix."""
    upstream = subprocess.run(
        ["git", "show", f"{UPSTREAM_COMMIT}:server/agents/interaction_agent/system_prompt.md"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return {"baseline": upstream, "fixed": build_system_prompt()}


def build_request(model: str, variant: str, case: Case, agents: list[AgentRecord], prompts: dict) -> dict:
    """One chat-completions body. Every body is checked, not just the first."""
    if not model.endswith(":free"):
        raise RefusedToSpend(f"{model} is not a ':free' model")
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": prompts[variant]},
            {"role": "user", "content": interaction_message(variant, agents, case.history, case.message)},
        ],
        "tools": get_tool_schemas(),
        "tool_choice": {"type": "function", "function": {"name": "send_message_to_agent"}},
        "temperature": 0,
    }


def cache_key(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _get_json(client: httpx.Client, path: str, api_key: str) -> dict:
    response = client.get(f"{API_URL}{path}", headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    response.raise_for_status()
    return response.json()


def _post_chat(client: httpx.Client, api_key: str, request: dict) -> dict:
    """POST once; on 429 wait as told and retry, at most twice."""
    for attempt in range(3):
        response = client.post(
            f"{API_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=request,
            timeout=120,
        )
        if response.status_code == 429 and attempt < 2:
            retry_after = response.headers.get("Retry-After", "")
            time.sleep(min(float(retry_after) if retry_after.isdigit() else 30, 120))
            continue
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenRouter returned {response.status_code}: {response.text[:300]}\n"
                "(If it mentions a data policy, allow free-model endpoints in your OpenRouter privacy settings.)"
            )
        payload = response.json()
        if not payload.get("choices"):  # an error in a 200 body; don't cache it as an answer
            raise RuntimeError(f"OpenRouter returned no choices: {str(payload)[:300]}")
        return payload
    raise RuntimeError("unreachable")


def send(model: str, pending: list[dict], cache: dict) -> None:
    api_key = get_settings().openrouter_api_key
    if not api_key:
        raise RefusedToSpend("OPENROUTER_API_KEY is not set (put it in .env)")

    with httpx.Client() as client:
        check_model_is_free(model, _get_json(client, "/models", api_key))
        spend_before = check_free_quota(_get_json(client, "/key", api_key), len(pending))
        print(f"Checks passed: {model} is free, quota covers {len(pending)} calls, key spend ${spend_before}")

        for i, request in enumerate(pending, start=1):
            if i > 1:
                time.sleep(SECONDS_BETWEEN_CALLS)
            response = _post_chat(client, api_key, request)
            check_response_cost(response)
            cache[cache_key(request)] = response
            save_cache(cache)  # after every call, so an interrupted run keeps its answers
            print(f"  {i}/{len(pending)} done")

        spend_after = check_free_quota(_get_json(client, "/key", api_key), 0)
        print(f"Key spend before ${spend_before}, after ${spend_after}")
        if spend_after != spend_before:
            raise RefusedToSpend("the key's spend changed during the run")


# ---------------------------------------------------------------- scoring

def chosen_agent(response: dict) -> Optional[str]:
    """The agent_name of the first send_message_to_agent call, if any."""
    message = ((response.get("choices") or [{}])[0]).get("message") or {}
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        if function.get("name") == "send_message_to_agent":
            try:
                return json.loads(function.get("arguments") or "{}").get("agent_name") or None
            except (json.JSONDecodeError, AttributeError):
                return None
    return None


def outcome(variant: str, case: Case, chosen: Optional[str], agents: list[AgentRecord]) -> str:
    """correct | duplicate (new agent for existing work) | wrong agent | no call."""
    if not chosen:
        return "no call"
    existing = resolve_agent(variant, chosen, agents)
    if case.expected_agent is None:
        return "correct" if existing is None else "wrong agent"
    if existing is None:
        return "duplicate"
    return "correct" if existing.name == case.expected_agent else "wrong agent"


def report(model: str, rows: list[dict]) -> str:
    kinds = list(dict.fromkeys(case.kind for case in CASES))
    lines = [
        f"Model: `{model}`, roster of {ROSTER_SIZE} agents, {len(CASES)} cases, temperature 0.",
        "",
        "| Version | " + " | ".join(kinds) + " | Correct | Duplicates | Wrong agent | No call | Prompt tokens (mean) |",
        "|---|" + "---|" * (len(kinds) + 5),
    ]
    for variant in VARIANTS:
        mine = [row for row in rows if row["variant"] == variant]
        by_kind = [
            f"{sum(r['outcome'] == 'correct' for r in mine if r['kind'] == kind)}/"
            f"{sum(r['kind'] == kind for r in mine)}"
            for kind in kinds
        ]
        counts = [sum(r["outcome"] == name for r in mine) for name in ("correct", "duplicate", "wrong agent", "no call")]
        tokens = [r["prompt_tokens"] for r in mine if r["prompt_tokens"]]
        mean_tokens = f"{sum(tokens) / len(tokens):,.0f}" if tokens else "n/a"
        lines.append(
            f"| {variant} | " + " | ".join(by_kind) + f" | {counts[0]}/{len(mine)} | "
            + " | ".join(map(str, counts[1:])) + f" | {mean_tokens} |"
        )

    lines += ["", "| Case | Expected | Baseline picked | Fixed picked |", "|---|---|---|---|"]
    for case in CASES:
        picks = {r["variant"]: r for r in rows if r["case"] == case.id}
        cells = [f"{picks[v]['chosen'] or '-'} ({picks[v]['outcome']})" for v in VARIANTS]
        lines.append(f"| {case.id} | {case.expected_agent or '(new agent)'} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=DEFAULT_MODEL, help="an OpenRouter ':free' model id")
    model = parser.parse_args(argv).model

    agents = build_roster(ROSTER_SIZE)
    prompts = system_prompts()
    planned = [
        (case, variant, build_request(model, variant, case, agents, prompts))
        for case in CASES
        for variant in VARIANTS
    ]
    cache = load_cache()
    pending = calls_to_send([request for _, _, request in planned], cache)
    print(f"{len(planned)} requests: {len(planned) - len(pending)} cached, {len(pending)} to send")
    if pending:
        send(model, pending, cache)

    rows = []
    for case, variant, request in planned:
        response = cache[cache_key(request)]
        chosen = chosen_agent(response)
        rows.append({
            "case": case.id,
            "kind": case.kind,
            "variant": variant,
            "chosen": chosen,
            "outcome": outcome(variant, case, chosen, agents),
            "prompt_tokens": (response.get("usage") or {}).get("prompt_tokens"),
        })
    text = report(model, rows)
    print(text)
    REPORT_PATH.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
