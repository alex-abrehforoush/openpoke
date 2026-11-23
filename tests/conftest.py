"""Shared pytest setup.

Every test runs with outbound network disabled. config.py loads .env at import
time, so a real OPENROUTER_API_KEY may be present while tests run; blocking
socket connections guarantees no test can ever reach OpenRouter (or Composio)
and spend money, no matter what the code under test tries to do.
"""

import socket

import pytest


def _refuse_connection(*args, **kwargs):
    raise RuntimeError("Network access is disabled in tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # Hostname lookups fail first, so a request to openrouter.ai stops before
    # any connection attempt; connect is blocked too for raw-IP requests.
    monkeypatch.setattr(socket, "getaddrinfo", _refuse_connection)
    monkeypatch.setattr(socket.socket, "connect", _refuse_connection)
