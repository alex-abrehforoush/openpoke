"""Agent roster: one small record per execution agent, stored in roster.json."""

import json
import fcntl
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ...logging_config import logger
from .log_store import _slugify

# Enough of the latest instructions to say what the agent is working on.
DESCRIPTION_MAX_CHARS = 150


@dataclass
class AgentRecord:
    """What the roster knows about one execution agent."""

    name: str
    description: str = ""  # latest instructions, shortened
    created_at: str = ""  # ISO 8601, UTC
    last_active_at: str = ""  # ISO 8601, UTC; "" sorts as oldest


def _utc_now_iso() -> str:
    # Microseconds keep agents touched in the same second (one turn fanning out
    # to several agents) in the order they were used. Same format everywhere,
    # so comparing the strings compares the times.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _record_from_json(item: object) -> Optional[AgentRecord]:
    if isinstance(item, str):  # original format: roster.json was a list of names
        return AgentRecord(name=item)
    if isinstance(item, dict) and item.get("name"):
        return AgentRecord(
            name=str(item["name"]),
            description=str(item.get("description", "")),
            created_at=str(item.get("created_at", "")),
            last_active_at=str(item.get("last_active_at", "")),
        )
    return None


class AgentRoster:
    """Roster of execution agents persisted as a JSON list of records."""

    def __init__(self, roster_path: Path):
        self._roster_path = roster_path
        self._agents: list[AgentRecord] = []
        self.load()

    def load(self) -> None:
        """Load agent records from roster.json."""
        if self._roster_path.exists():
            try:
                with open(self._roster_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        records = (_record_from_json(item) for item in data)
                        self._agents = [record for record in records if record]
            except Exception as exc:
                logger.warning(f"Failed to load roster.json: {exc}")
                self._agents = []
        else:
            self._agents = []
            self.save()

    def save(self) -> None:
        """Save agent records to roster.json with file locking."""
        max_retries = 5
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                self._roster_path.parent.mkdir(parents=True, exist_ok=True)

                # Open file and acquire exclusive lock
                with open(self._roster_path, 'w') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    try:
                        json.dump([asdict(record) for record in self._agents], f, indent=2)
                        return
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            except BlockingIOError:
                # Lock is held by another process
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.warning("Failed to acquire lock on roster.json after retries")
            except Exception as exc:
                logger.warning(f"Failed to save roster.json: {exc}")
                break

    def find(self, agent_name: str) -> Optional[AgentRecord]:
        """Return the agent with this name, ignoring case and punctuation.

        Names are compared by the same slug the log store uses for file names,
        so two spellings that share a log file are also the same roster entry.
        """
        key = _slugify(agent_name)
        return next((r for r in self._agents if _slugify(r.name) == key), None)

    def touch(self, agent_name: str, instructions: str) -> AgentRecord:
        """Record that the agent just received instructions, creating it if new."""
        now = _utc_now_iso()
        record = self.find(agent_name)
        if record is None:
            record = AgentRecord(name=agent_name, created_at=now)
            self._agents.append(record)
        record.description = " ".join(instructions.split())[:DESCRIPTION_MAX_CHARS]
        record.last_active_at = now
        self.save()
        return record

    def get_agents(self) -> list[AgentRecord]:
        """Get all agent records."""
        return list(self._agents)

    def clear(self) -> None:
        """Clear the agent roster."""
        self._agents = []
        try:
            if self._roster_path.exists():
                self._roster_path.unlink()
            logger.info("Cleared agent roster")
        except Exception as exc:
            logger.warning(f"Failed to clear roster.json: {exc}")


_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_ROSTER_PATH = _DATA_DIR / "execution_agents" / "roster.json"

_agent_roster = AgentRoster(_ROSTER_PATH)


def get_agent_roster() -> AgentRoster:
    """Get the singleton roster instance."""
    return _agent_roster
