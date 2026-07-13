"""Entrypoint asynchrone : ack immédiat + run en tâche de fond + libération.

``bedrock_agentcore`` n'est pas installé dans l'env de test : on injecte un faux
module AVANT d'importer ``agent`` pour piloter/observer ``add_async_task`` et
``complete_async_task``.
"""
import sys
import threading
import time
import types

import pytest


# --- faux SDK AgentCore, injecté avant l'import de agent.py ------------------
class _FakeApp:
    def __init__(self, **kwargs):
        self.added = []
        self.completed = []

    def entrypoint(self, fn):
        self.entry = fn
        return fn

    def add_async_task(self, name):
        self.added.append(name)
        return f"task-{len(self.added)}"

    def complete_async_task(self, task_id):
        self.completed.append(task_id)
        return True

    def run(self):  # pragma: no cover
        pass


_fake_module = types.ModuleType("bedrock_agentcore")
_fake_module.BedrockAgentCoreApp = _FakeApp
sys.modules["bedrock_agentcore"] = _fake_module

import agent as agent_mod  # noqa: E402


class _Ctx:
    session_id = "session-abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture(autouse=True)
def _reset_app():
    """Repart d'un état d'app propre avant chaque test."""
    agent_mod.app.added.clear()
    agent_mod.app.completed.clear()
    yield


def _wait_completed(timeout=2.0):
    deadline = time.time() + timeout
    while not agent_mod.app.completed and time.time() < deadline:
        time.sleep(0.01)


def test_invalid_payload_returns_invalid_request():
    res = agent_mod.invoke({}, _Ctx())
    assert res["result"]["status"] == "invalid_request"
    # Aucune tâche asynchrone lancée sur un payload invalide.
    assert agent_mod.app.added == []


def test_valid_payload_accepts_and_runs_in_background(monkeypatch):
    done = threading.Event()
    calls = []

    def fake_run(request, *, session_id, logger):
        calls.append(request)
        done.set()
        return {"result": {"status": "complete"}}

    monkeypatch.setattr(agent_mod, "run_documentation", fake_run)

    res = agent_mod.invoke(
        {"repo_full_name": "acme/widget", "pr_number": 42, "correlation_id": "c1"},
        _Ctx(),
    )
    # Ack immédiat, non bloquant.
    assert res["result"]["status"] == "accepted"
    assert agent_mod.app.added == ["documentation_run"]

    # Le run s'exécute bien en tâche de fond.
    assert done.wait(timeout=2.0)
    _wait_completed()
    assert agent_mod.app.completed == ["task-1"]  # tâche libérée (/ping -> Healthy)
    assert calls and calls[0].repo_full_name == "acme/widget"


def test_background_failure_still_completes_task(monkeypatch):
    def boom(request, *, session_id, logger):
        raise RuntimeError("échec run")

    monkeypatch.setattr(agent_mod, "run_documentation", boom)

    res = agent_mod.invoke({"repo_full_name": "acme/widget", "pr_number": 1}, _Ctx())
    assert res["result"]["status"] == "accepted"
    # Même en cas d'échec du run, la tâche asynchrone est libérée (finally).
    _wait_completed()
    assert agent_mod.app.completed == ["task-1"]
