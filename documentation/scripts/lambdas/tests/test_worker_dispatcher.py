"""Task 9/10 — Lambda worker : sessionId, classification erreurs."""
import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "worker-dispatcher", "handler.py")
_spec = importlib.util.spec_from_file_location("worker_handler", _PATH)
worker = importlib.util.module_from_spec(_spec)
import sys as _sys
_sys.modules["worker_handler"] = worker
_spec.loader.exec_module(worker)


def test_session_id_min_length():
    sid = worker._session_id("abc", "42")
    assert len(sid) >= 33


def test_session_id_truncates_long():
    sid = worker._session_id("x" * 100, "42")
    assert len(sid) <= 64


def test_invoke_requires_runtime_arn(monkeypatch):
    monkeypatch.setattr(worker, "RUNTIME_ARN", "")
    with pytest.raises(worker.PermanentError):
        worker._invoke_runtime({"repo_full_name": "a/b", "pr_number": 1})


def test_invoke_rejects_invalid_message(monkeypatch):
    monkeypatch.setattr(worker, "RUNTIME_ARN", "arn:runtime")
    with pytest.raises(worker.PermanentError):
        worker._invoke_runtime({"pr_number": 1})  # repo manquant


def test_handler_absorbs_permanent_error(monkeypatch):
    monkeypatch.setattr(worker, "RUNTIME_ARN", "arn:runtime")

    def boom(_msg):
        raise worker.PermanentError("bad")

    monkeypatch.setattr(worker, "_invoke_runtime", boom)
    # Un message permanent ne fait pas échouer le handler (pas de rejeu).
    result = worker.lambda_handler({"Records": [{"body": '{"repo_full_name":"a/b","pr_number":1}'}]}, None)
    assert result["processed"] == 0
