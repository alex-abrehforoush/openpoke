# OpenPoke: agent overload fix

This fork fixes OpenPoke's **agent overload** problem, adds tests and evaluators for the fix, and lists other problems I found with a sketch of how I'd fix each one. The original README follows at the end, unchanged.

[Where it shows up](#1-where-agent-overload-shows-up) · [The fix](#2-the-fix) · [How I tested it](#3-how-i-tested-it) · [Evaluators and results](#4-evaluators-and-results) · [Other problems](#5-other-problems-i-found) · [How I used AI](#6-how-i-used-ai)

## Summary

| | |
|---|---|
| **Problem** | Every execution agent ever created is listed, by name only, in every interaction-agent request, and the list only grows. Near-duplicate names add more agents, and each execution agent's own prompt carries its entire history. |
| **Fix** | The interaction agent sees at most 10 agents: the 5 used most recently, plus up to 5 older ones whose name or description shares words with the current message, each with a short description and when it was last used. Agents that aren't listed still exist and are reused by name. Near-duplicate names map to the existing agent, and each execution agent sees only its last 10 requests. |
| **Evidence** | Offline eval at 300 agents: the agent list drops from ~2,531 to ~293 tokens, and the right agent is still listed for 10/10 recent and keyword callbacks. Near-duplicate names reuse the existing agent 7/10 times (0/10 before). Live eval (free Nemotron 3 Ultra, 300 agents): 40% fewer prompt tokens per call (5,978 → 3,569) and the same routing on recent, keyword and new-task cases (16/16). But all 4 paraphrased callbacks were missed (3 duplicates, 1 wrong agent), where the full list got them right. On this model the benefit is a bounded prompt, not better routing. |
| **Tests** | 37 pytest tests, about 2 seconds, with network access blocked. |

One commit per step, on branch `fix/agent-overload`:

| Commit | Step |
|---|---|
| `0caec47` | Test scaffolding, plus a failing test that reproduces the overload |
| `29bef7e` | A record per agent (description, timestamps); near-duplicate names merge |
| `6d51ad1` | The interaction agent sees recent and matching agents, at most 10 |
| `6f1b396` | Each execution agent's history is capped at its last 10 requests |
| `764c110` | Offline evaluator, and a live evaluator that only runs on free models |
| `6f12b87` | An agent's description stays its first instructions (fixes a regression found in review) |
| `1ed8254` | Scheduled runs count as agent activity (fixes a regression found in review) |

## 1. Where agent overload shows up

The explainer's "Execution Agent Overload" section names it: execution agents "persist indefinitely", and "the entire roster of Execution Agents is passed to the Interaction Agent with every request", which "creates a relevance problem". In the code (links go to upstream commit `5b5f635`):

1. **The roster only grows.** [`roster.py:63-67`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/services/execution/roster.py#L63-L67): `add_agent` appends a name. Nothing removes one, except `clear()`, which wipes everything when the user clears the chat.
2. **Every agent goes into every interaction-agent request, name only.** [`agent.py:29`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/agents/interaction_agent/agent.py#L29) adds `<active_agents>` to every request, and [`agent.py:45-58`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/agents/interaction_agent/agent.py#L45-L58) renders every name in the roster. That covers every user message, every batch of agent results and every email alert. It's also re-sent on each tool-loop iteration inside those turns (up to 8). With names only, the model can't tell what an agent did or when.
3. **Reusing an agent needs its exact name.** [`tools.py:117-120`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/agents/interaction_agent/tools.py#L117-L120): sending to "email to alice" when "Email to Alice" exists creates a second agent with an empty history. The prompt tells the model to reuse agents ([`system_prompt.md:19`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/agents/interaction_agent/system_prompt.md#L19)) but gives it only names to go on.
4. **Each execution agent sees its whole history.** [`runtime.py:33`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/agents/execution_agent/runtime.py#L33) builds `ExecutionAgent(agent_name)` with no limit, so `conversation_limit` stays `None` ([`agent.py:39`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/agents/execution_agent/agent.py#L39)). The agent's full log goes into its system prompt on every run. Reused agents and reminders that fire again and again grow it without bound. The limit was already implemented ([`agent.py:77-90`](https://github.com/shlokkhemani/openpoke/blob/5b5f635935a64ab37884c025d70abb0ed731c094/server/agents/execution_agent/agent.py#L77-L90)) but never turned on.

**The effect:** the interaction agent's input grows with everything the user has ever delegated, so every turn gets more tokens, cost and latency. Picking the right agent from a long list of bare names gets harder. A wrong pick creates a duplicate, which makes the list longer still.

## 2. The fix

| What | Where | Why |
|---|---|---|
| One record per agent: name, description, created and last-active times. The old names-only `roster.json` still loads. | [roster.py:19](server/services/execution/roster.py#L19) | The model needs more than a name to pick an agent, and recency needs a timestamp. |
| List at most 10 agents: the 5 used most recently, then up to 5 older ones ranked by words shared with the current message. | [agent.py:18](server/agents/interaction_agent/agent.py#L18), [agent.py:80](server/agents/interaction_agent/agent.py#L80) | The list stays bounded however many agents exist. Follow-ups ("send it") almost always go to a recent agent. Callbacks ("did Priya reply?") usually share a word with the agent they're about. |
| Show each listed agent's description and last-active time, in the user's timezone. | [agent.py:97](server/agents/interaction_agent/agent.py#L97) | The model can judge relevance instead of guessing from a name. |
| One prompt line saying the list is partial and that unlisted agents are reused by their exact name. | [system_prompt.md:20](server/agents/interaction_agent/system_prompt.md#L20) | Without it, the model would assume an unlisted agent doesn't exist. |
| Match names ignoring case and punctuation, using the slug the log files already use. | [roster.py:101](server/services/execution/roster.py#L101), [tools.py:114-119](server/agents/interaction_agent/tools.py#L114-L119) | "email to alice!" and "Email to Alice" already shared a log file. Now they share one roster entry too, kept under the stored spelling, which triggers are keyed by. |
| Each execution agent sees only its last 10 requests. | [runtime.py:29-36](server/agents/execution_agent/runtime.py#L29-L36) | This turns on the existing, unused limit. |
| An agent's description is its first instructions and is never overwritten. | [roster.py:110](server/services/execution/roster.py#L110) | Follow-ups are often just "send it". Overwriting would hide what the agent is for from keyword matching. |
| A scheduled (trigger) run updates the agent's last-active time. | [trigger_scheduler.py:85-89](server/services/trigger_scheduler.py#L85-L89) | Otherwise a reminder set up months ago never counts as recent, even right after it fires and the user replies "snooze it". |

### Why this design
- **It's the explainer's own suggestion, made cheap.** The article suggests "a hot cache of recently active agents" and "semantic search over agent descriptions". The recent slots are the hot cache. Keyword overlap stands in for semantic search: it needs no embedding model, adds no API call, latency or cost, and gives the same answer every time. That makes it unit-testable and the offline eval deterministic.
- **Nothing is deleted or archived.** Agents that aren't listed keep their logs, triggers and names. They're reused when the model sends to their exact name, for example one it sees in the conversation history.
- **The numbers are judgment calls, kept as named constants.** 5 + 5 agents comes to about 300 tokens. Ten past requests are enough for an agent to continue a thread. 150 characters is about one sentence of instructions. The offline eval makes other values quick to try.

### Known limits (measured)
- **Paraphrased callbacks are missed.** "When are my teeth getting cleaned?" shares no word with the "Dentist Appointment" agent ("…book a cleaning"), so that agent isn't listed (0/4 in the offline eval). In the live eval, all 4 paraphrased callbacks went wrong (3 duplicates, 1 wrong agent), while the full list got all 4 right. The model can still reach such an agent if it picks the same name, or if the name appears in the conversation history.
- **One shared word is enough to list an older agent,** and that can put the wrong one in front of the model. In the live eval, "Did that job I was offered say how long I have to decide?" listed "Recruiter Follow-up" only because both contain "say", and the model sent the question there.
- **With few agents, the list is slightly bigger than before:** about 265 vs 212 tokens at 25 agents, because descriptions are included. The two cross at around 30–35 agents.
- **Name variants that use different words still create a new agent,** for example "Email Priya" vs "Email to Priya" (3 of the 10 variants in the eval).

### What I'd do next for agent overload
1. **Search a growing word set, and show a short description.** Keep the distinct content words from every instruction an agent receives, separate from the description that's displayed. Score matches by how rare each word is across agents (TF-IDF): "venue", found in one agent, counts a lot, while "email", found in 120, counts almost nothing. Without that weighting, agents reused for many tasks collect words and win every match.
2. **Pin the agents the user is replying to.** When results are handed to the interaction agent ([batch_manager.py:137-144](server/agents/execution_agent/batch_manager.py#L137-L144)), record which agents reported and when, and always list them, e.g. "Gym Reminder reported at 07:00". It has to be a list, because results from several agents arrive combined in one message. It has to carry a time, because email-watcher alerts arrive the same way with no agent behind them, so "the last message came from X" could be false.
3. **Let agents keep their own summary,** for example through a tool the execution agent calls at the end of a run. I deferred this for four reasons:
   - It changes the execution agent's output contract.
   - It needs a fallback when a run fails or times out.
   - It can't be tested deterministically.
   - A summary written while reading untrusted email would be shown to the interaction agent on every later turn, which is a lasting prompt-injection risk.
4. **Better recall for paraphrases:** the live eval shows these misses happen. The explainer's "semantic search over agent descriptions" (embeddings) is the direct fix, at the cost of an embedding model and its latency.

## 3. How I tested it

- **Tests first.** The first commit added a test reproducing the overload (300 agents listed where 30 were before), marked as an expected failure. It flipped to passing with the fix. Every later test was run against the code before its fix, to see it fail. For the selection settings and the scheduler change, I also broke the code on purpose and checked that the tests catch it: no keyword slots, 1 recent slot, an unbounded list, and the scheduler line removed.
- **No network in tests.** An autouse fixture in [tests/conftest.py](tests/conftest.py) blocks DNS lookups and socket connections. [tests/test_no_network.py](tests/test_no_network.py) checks that a real OpenRouter call fails. `config.py` loads `.env` on import, so this matters even when a real key is present.

| Test file | What it checks |
|---|---|
| [test_agent_overload.py](tests/test_agent_overload.py) | End to end through prompt construction: the list stays at 10 for 30 and for 300 agents; an old agent is listed when the message mentions it, and not otherwise; a short follow-up doesn't hide it. |
| [test_agent_selection.py](tests/test_agent_selection.py) | Selection rules (recency, keyword ranking and ties, stopwords, the cap) and rendering (escaping, timezone). |
| [test_roster.py](tests/test_roster.py) | Records persist, timestamps update, the description is kept, near-duplicate names merge (including through `send_message_to_agent`), and the old roster format loads. |
| [test_execution_history.py](tests/test_execution_history.py) | An execution agent's prompt keeps exactly its last 10 requests. |
| [test_trigger_activity.py](tests/test_trigger_activity.py) | A scheduled run updates last-active and keeps the description. |
| [test_offline_eval.py](tests/test_offline_eval.py) | Guards the offline eval's numbers against regressions, and checks the eval builds exactly the message the server builds. |
| [test_live_eval.py](tests/test_live_eval.py) | The live eval's zero-spend checks and its scoring, with no network. |
| [test_no_network.py](tests/test_no_network.py) | The network block works. |

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements-dev.txt
.venv/bin/python -m pytest              # 37 tests, no network
.venv/bin/python -m evals.offline_eval  # about 1 second, no network
```

**Not tested:** the full app end to end with Gmail (Composio) and a real model. The default models are paid (`anthropic/claude-sonnet-4`), and I kept this work at zero API spend. The live eval below is the closest substitute: it sends the interaction agent's real request to a free model.

## 4. Evaluators and results

Both evaluators use the same made-up dataset ([evals/dataset.py](evals/dataset.py)):
- **The roster:** 20 hand-written agents plus seeded distractor agents doing everyday chores ("Meeting with Nadia", "Invoice from Omar"), up to 340 agents in total.
- **The cases:** 20 labelled cases, in four kinds:

| Kind | Cases | Example | Right answer |
|---|---|---|---|
| Recent follow-up | 4 | "looks good, send it" (right after a draft) | The agent that was just used |
| Keyword callback | 6 | "Did Priya get back to us about the venue deposit?" | An older agent that shares words with the message |
| Paraphrase callback | 4 | "When are my teeth getting cleaned?" | "Dentist Appointment", which shares no words with it |
| New task | 6 | "Find a good Italian restaurant near the office for lunch on Friday." | A new agent |

Each case is built twice:
- **Baseline:** upstream's system prompt and agent list (names only).
- **Fixed:** the current code.

Both are built through the real `prepare_message_with_history` ([evals/harness.py](evals/harness.py)), and a test checks the result is identical to what the server builds.

### Offline eval: what the interaction agent is shown
Deterministic, no network, about 1 second: `.venv/bin/python -m evals.offline_eval` (output also in [evals/results/offline_results.md](evals/results/offline_results.md)).

| Agents in roster | Version | Agents listed per turn (mean / max) | Agent list, ~tokens | Recent follow-up | Keyword callback | Paraphrase callback |
|---|---|---|---|---|---|---|
| 25 | baseline | 25.0 / 25 | 212 | 4/4 | 6/6 | 4/4 |
| 25 | fixed | 6.5 / 10 | 265 | 4/4 | 6/6 | 0/4 |
| 100 | baseline | 100.0 / 100 | 847 | 4/4 | 6/6 | 4/4 |
| 100 | fixed | 7.4 / 10 | 294 | 4/4 | 6/6 | 0/4 |
| 300 | baseline | 300.0 / 300 | 2,531 | 4/4 | 6/6 | 4/4 |
| 300 | fixed | 7.4 / 10 | 293 | 4/4 | 6/6 | 0/4 |

Near-duplicate names that reuse the existing agent: 0/10 for the baseline, 7/10 for the fix.

**How to read it:**
- **Size.** The fixed list stays at about 7 agents and 290 tokens however big the roster gets, while the baseline grows with it.
- **Recall.** For recent and keyword callbacks, the right agent is still in front of the model. The baseline always "finds" it because it lists everything; the price is the size, and names with no context.
- **Paraphrases** are the known miss.

### Live eval: what the model actually does
This eval is opt-in and runs only on free models. Command: `.venv/bin/python -m evals.live_eval` (default model `nvidia/nemotron-3-ultra-550b-a55b:free`; change it with `--model`; needs `OPENROUTER_API_KEY` in `.env` only for answers that aren't already cached).

**How it works:**
- **One call per case.** Each case sends the interaction agent's real request (system prompt, history, agent list, message) with a 300-agent roster, at temperature 0. The model is required to call `send_message_to_agent`. That keeps each case to one call and makes the answer a name, so this eval measures routing, not whether the model would delegate at all.
- **Exact scoring, no LLM judge.** The chosen `agent_name` is scored with each version's own name matching (exact name before the fix, slug after) as correct, duplicate (a new agent for existing work), wrong agent, or no call. It also reports the prompt token counts the API returns.

**Zero-spend checks (unit-tested).** Before sending anything, it refuses unless:
1. the model id ends in `:free`;
2. every price OpenRouter lists for that model is 0;
3. today's free-request quota covers the run.

During a run, it:
- stops on any response that reports a cost;
- compares the key's total spend before and after the run;
- caps a run at 45 calls (the free tier allows 50 a day) and spaces calls 3.5 seconds apart;
- caches every response in `evals/results/live_cache.json`, so re-runs send nothing and the results can be re-scored without a key.

**Results:** `nvidia/nemotron-3-ultra-550b-a55b:free`, 300-agent roster, 20 cases, 40 calls, $0.00 spent (checked before and after). The per-case table is in [evals/results/live_results.md](evals/results/live_results.md).

| Version | Recent | Keyword | Paraphrase | New task | Correct | Duplicates | Wrong agent | Prompt tokens per call (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | 4/4 | 6/6 | 4/4 | 6/6 | 20/20 | 0 | 0 | 5,978 |
| fixed | 4/4 | 6/6 | 0/4 | 6/6 | 16/20 | 3 | 1 | 3,569 |

**What it shows:**
- **Prompt size.** The fix made each interaction-agent call 2,409 tokens (40%) smaller at 300 agents. That's close to the offline estimate (~2,240 tokens) from the agent list's size. The saving grows with every agent the user creates, and applies to each of the up to 8 model calls in a turn.
- **Routing.** It didn't improve; it got worse on paraphrases. This model routed all 20 cases correctly from a 300-name list, so at this size the long list didn't confuse it. The fix matched it on recent follow-ups, keyword callbacks and new tasks, and missed all 4 paraphrased callbacks:
  - 3 duplicates, for example a new "Dental Appointment Check" instead of the existing "Dentist Appointment";
  - 1 wrong agent: the "say" case above, the worse failure, because the follow-up goes to an agent with the wrong context.
- **Conclusion.** On this evidence the fix's benefit is a smaller prompt that stays bounded, not better routing, and its cost is paraphrased callbacks. I didn't find the roster size at which the full list starts to hurt routing. That would need larger rosters and more requests than the free tier's 50 a day.

**Note on the model:** I planned to use `google/gemma-4-31b-it:free`, but Google's free endpoint was rate-limited upstream at run time. It rejected both attempts, and my quota was unaffected. Nvidia's free Nemotron 3 Ultra was the largest free alternative with full uptime. It's now the default, so `python -m evals.live_eval` re-scores the committed cache without a key.

## 5. Other problems I found

The task was to fix agent overload, so I've kept these out of the code. Each has its location and a sketch of the fix.

### 5.1 "Ask before sending" is only a prompt rule, and reply and forward skip it
[execution_agent/system_prompt.md:3](server/agents/execution_agent/system_prompt.md#L3) says never to send a draft without explicit confirmation. But [`gmail_reply_to_thread`](server/agents/execution_agent/tools/gmail.py#L404) and [`gmail_forward_email`](server/agents/execution_agent/tools/gmail.py#L387) send immediately, with no draft and no check in code. A misread instruction, or a prompt injection in an email the agent reads, can send mail as the user.

**Fix:** make it structural. Reply and forward create a draft in the thread instead of sending, and the one sending tool refuses unless the user approved that draft.

```python
# server/services/approvals.py (new)
_approved_drafts: set[str] = set()

def approve(draft_id: str) -> None:
    _approved_drafts.add(draft_id)

def consume(draft_id: str) -> bool:
    """True once per approval."""
    if draft_id in _approved_drafts:
        _approved_drafts.remove(draft_id)
        return True
    return False

# Interaction agent: a new tool, offered only on <new_user_message> turns,
# so an agent result or an email can't approve anything.
def approve_draft(draft_id: str) -> ToolResult:
    approve(draft_id)
    return ToolResult(success=True, payload={"approved": draft_id})

# server/agents/execution_agent/tools/gmail.py
def gmail_execute_draft(draft_id: str) -> Dict[str, Any]:
    if not consume(draft_id):
        return {"error": "The user has not approved this draft. Show it to them first."}
    ...  # existing send
```

### 5.2 Interaction-agent turns run at the same time
Three places start a turn as an independent task:
- user messages ([chat_handler.py:47](server/services/conversation/chat_handler.py#L47));
- agent results ([batch_manager.py:193](server/agents/execution_agent/batch_manager.py#L193));
- email alerts ([importance_watcher.py:226](server/services/gmail/importance_watcher.py#L226)).

Nothing puts them in order, so two turns can read the same transcript and both reply, or both delegate the same task. The `wait` tool ("wait silently when a message is already in conversation history") works around this in the prompt.

```python
# server/agents/interaction_agent/runtime.py
_TURN_LOCK = asyncio.Lock()  # one interaction-agent turn at a time

async def execute(self, user_message: str) -> InteractionResult:
    async with _TURN_LOCK:
        ...  # existing body; each turn now sees the previous turn's replies

async def handle_agent_message(self, agent_message: str) -> InteractionResult:
    async with _TURN_LOCK:
        ...
```

### 5.3 Gmail calls block the whole server
Composio's client is synchronous ([gmail/client.py:483](server/services/gmail/client.py#L483)), and the execution runtime calls tools directly on the event loop ([runtime.py:234](server/agents/execution_agent/runtime.py#L234)). Every Gmail call freezes all other agents, HTTP requests and the scheduler until it returns, and the 90-second timeout can't interrupt it. That's part of the slowness the explainer mentions.

```python
# server/agents/execution_agent/runtime.py, in _execute_tool
if inspect.iscoroutinefunction(tool_func):
    result = await tool_func(**arguments)
else:
    # Sync tools (Composio) run in a worker thread; the log store already locks per agent.
    result = await asyncio.to_thread(tool_func, **arguments)
```

### 5.4 The same agent can run twice at once
Nothing stops two runs of one agent from overlapping, for example a user follow-up while a reminder fires. Both read the same log, append to it in an interleaved order, and may both act, for example by sending twice. There's no limit on parallel runs overall either. The scheduler also builds its own `ExecutionBatchManager` for every firing ([trigger_scheduler.py:98](server/services/trigger_scheduler.py#L98)), so a limit inside the shared manager wouldn't cover reminders.

```python
# server/agents/execution_agent/batch_manager.py
_AGENT_LOCKS: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)  # keyed by slug
_RUN_SLOTS = asyncio.Semaphore(8)  # parallel runs across all agents

    # in execute_agent:
    async with _RUN_SLOTS, _AGENT_LOCKS[_slugify(agent_name)]:
        result = await asyncio.wait_for(runtime.execute(instructions), timeout=self.timeout_seconds)

# ...plus one shared manager (get_execution_batch_manager()) used by tools.py and the scheduler.
```

### 5.5 One global batch holds back fast results
Results go to the interaction agent only once every run in the current batch has finished ([batch_manager.py:137](server/agents/execution_agent/batch_manager.py#L137)). A 2-second lookup waits for a slow run in the same batch, up to the 90-second timeout. Runs started while a batch is open join it and stretch the wait further.

```python
# Dispatch each result as soon as it finishes; the turn lock from 5.2 keeps turns in order.
async def _complete_execution(self, batch_id, result, agent_name):
    await self._dispatch_to_interaction_agent(self._format_batch_payload([result]))
```

The trade-off is one interaction-agent call per result instead of per batch. A middle ground is to dispatch whatever has finished every few seconds.

### 5.6 `roster.json` can be wiped
[roster.py:82](server/services/execution/roster.py#L82) opens the file with `'w'`, which empties it before the lock is taken, and `load()` reads without the lock. A read during a write, or a crash mid-write, sees an empty or partial file. `load()` then resets the roster to `[]` ([roster.py:67](server/services/execution/roster.py#L67)), and the next save makes the loss permanent.

```python
def save(self) -> None:
    self._roster_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = self._roster_path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(record) for record in self._agents], indent=2))
    os.replace(tmp, self._roster_path)  # atomic: readers see the old file or the new one
```

`load()` should also keep the current list on a parse error, instead of resetting it.

### 5.7 Every model is hard-coded to a paid model
All five model settings default to `anthropic/claude-sonnet-4` ([config.py:54-58](server/config.py#L54-L58)). Unlike the other settings in the same class, none can be changed from the environment, so switching models means editing code. The explainer estimates 10–15 model calls per user message, and the summarizer and email classifier are good candidates for a cheaper model.

```python
interaction_agent_model: str = Field(default=os.getenv("OPENPOKE_INTERACTION_MODEL", "anthropic/claude-sonnet-4"))
summarizer_model: str = Field(default=os.getenv("OPENPOKE_SUMMARIZER_MODEL", "anthropic/claude-sonnet-4"))
# ...the same for the other three
```

### 5.8 Model calls are never retried
[openrouter_client/client.py:70-87](server/openrouter_client/client.py#L70-L87) makes a single attempt. One 429 or 5xx fails the whole turn. For a user message, the user gets no reply, because the failed turn returns an empty response and the error is only logged.

```python
for attempt in range(3):
    response = await client.post(url, headers=_headers(api_key=api_key), json=payload, timeout=60.0)
    if response.status_code in (429, 500, 502, 503) and attempt < 2:
        await asyncio.sleep(2 ** attempt)  # or the Retry-After header, when present
        continue
    break
```

## 6. How I used AI

I used Claude Code (Claude Opus 5.5) throughout.

- **What I decided:**
  - The ground rules, before any code: I must be able to explain every line; minimal and correct beats clever; and zero API spend, meaning free models only, enforced in code.
  - The approach (recency plus keyword matching), from the options Claude laid out.
  - The workflow: one small commit at a time, with Claude explaining each before I approved the next.
  - The scope: fix agent overload only, and write up the rest.
  - For the two regressions found in review, I proposed the fuller designs now listed under "What I'd do next", had Claude critique them, and chose minimal fixes for this submission.
- **What Claude did:** traced the overload through the code; wrote the code, tests, evaluators and this README; and ran everything.
- **How the work was checked:**
  - Every test was seen failing before its fix.
  - Key changes were broken on purpose to confirm the tests catch them.
  - Tests can't reach the network.
  - The live eval's spend checks are unit-tested.
- **Where the AI was wrong, and what review caught:**
  - **A wrong claim about charges.** Claude first said a zero-balance OpenRouter account can't be charged. OpenRouter's docs don't promise that, so the live eval relies on its own checks: the `:free` id, the live $0 price, the per-response cost, and total spend before and after.
  - **Two regressions in its own fix,** found in a design review: follow-ups overwrote the description that keyword matching relies on, and scheduled runs didn't count as recent activity. Both are fixed (`6f12b87`, `1ed8254`). The eval dataset hadn't caught the first, because it gave every agent a detailed description.
  - **Bugs caught by tests during development.**
    - The network block first stopped only connections, but httpx tries IPv4 and IPv6 in parallel.
    - Timestamps with one-second resolution tied, which scrambled the recency order.

---

*The original OpenPoke README follows, unchanged.*

# OpenPoke 🌴

OpenPoke is a simplified, open-source take on [Interaction Company’s](https://interaction.co/about) [Poke](https://poke.com/) assistant—built to show how a multi-agent orchestration stack can feel genuinely useful. It keeps the handful of things Poke is great at (email triage, reminders, and persistent agents) while staying easy to spin up locally.

- Multi-agent FastAPI backend that mirrors Poke's interaction/execution split, powered by [OpenRouter](https://openrouter.ai/).
- Gmail tooling via [Composio](https://composio.dev/) for drafting/replying/forwarding without leaving chat.
- Trigger scheduler and background watchers for reminders and "important email" alerts.
- Next.js web UI that proxies everything through the shared `.env`, so plugging in API keys is the only setup.

## Requirements
- Python 3.10+
- Node.js 18+
- npm 9+

## Quickstart
1. **Clone and enter the repo.**
   ```bash
   git clone https://github.com/shlokkhemani/OpenPoke
   cd OpenPoke
   ```
2. **Create a shared env file.** Copy the template and open it in your editor:
   ```bash
   cp .env.example .env
   ```
3. **Get your API keys and add them to `.env`:**
   
   **OpenRouter (Required)**
   - Create an account at [openrouter.ai](https://openrouter.ai/)
   - Generate an API key
   - Replace `your_openrouter_api_key_here` with your actual key in `.env`
   
   **Composio (Required for Gmail)**
   - Sign in at [composio.dev](https://composio.dev/)
   - Create an API key
   - Set up Gmail integration and get your auth config ID
   - Replace `your_composio_api_key_here` and `your_gmail_auth_config_id_here` in `.env`
4. **(Required) Create and activate a Python 3.10+ virtualenv:**
   ```bash
   # Ensure you're using Python 3.10+
   python3.10 -m venv .venv
   source .venv/bin/activate
   
   # Verify Python version (should show 3.10+)
   python --version
   ```
   On Windows (PowerShell):
   ```powershell
   # Use Python 3.10+ (adjust path as needed)
   python3.10 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   
   # Verify Python version
   python --version
   ```

5. **Install backend dependencies:**
   ```bash
   pip install -r server/requirements.txt
   ```
6. **Install frontend dependencies:**
   ```bash
   npm install --prefix web
   ```
7. **Start the FastAPI server:**
   ```bash
   python -m server.server --reload
   ```
8. **Start the Next.js app (new terminal):**
   ```bash
   npm run dev --prefix web
   ```
9. **Connect Gmail for email workflows.** With both services running, open [http://localhost:3000](http://localhost:3000), head to *Settings → Gmail*, and complete the Composio OAuth flow. This step is required for email drafting, replies, and the important-email monitor.

The web app proxies API calls to the Python server using the values in `.env`, so keeping both processes running is required for end-to-end flows.

## Project Layout
- `server/` – FastAPI application and agents
- `web/` – Next.js app
- `server/data/` – runtime data (ignored by git)

## License
MIT — see [LICENSE](LICENSE).
