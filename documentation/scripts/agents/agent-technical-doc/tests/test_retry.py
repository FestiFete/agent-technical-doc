"""Retry avec backoff — détection des erreurs transitoires + rejeu (sans sleep réel)."""
import pytest

from docagent.retry import is_transient_error, retry_call


class _Boom(Exception):
    """Exception avec attribut transient (façon GitHubError)."""

    def __init__(self, transient):
        super().__init__("boom")
        self.transient = transient


class _NamedThrottle(Exception):
    pass


_NamedThrottle.__name__ = "ThrottlingException"


def test_is_transient_via_attribute():
    assert is_transient_error(_Boom(True)) is True
    assert is_transient_error(_Boom(False)) is False


def test_is_transient_via_class_name():
    assert is_transient_error(_NamedThrottle()) is True


def test_is_transient_via_botocore_code():
    exc = Exception()
    exc.response = {"Error": {"Code": "ThrottlingException"}}
    assert is_transient_error(exc) is True
    exc.response = {"Error": {"Code": "AccessDenied"}}
    assert is_transient_error(exc) is False


def test_retry_succeeds_after_transient():
    calls = {"n": 0}
    slept = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Boom(True)
        return "ok"

    out = retry_call(fn, attempts=3, sleep=slept.append)
    assert out == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2  # deux backoffs avant le succès


def test_retry_gives_up_after_attempts():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _Boom(True)

    with pytest.raises(_Boom):
        retry_call(fn, attempts=3, sleep=lambda _d: None)
    assert calls["n"] == 3


def test_retry_does_not_retry_permanent():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _Boom(False)  # non transitoire

    with pytest.raises(_Boom):
        retry_call(fn, attempts=5, sleep=lambda _d: None)
    assert calls["n"] == 1  # aucune nouvelle tentative


def test_retry_backoff_is_exponential_and_capped():
    slept = []

    def fn():
        raise _Boom(True)

    with pytest.raises(_Boom):
        retry_call(fn, attempts=5, base_delay=1.0, max_delay=4.0, sleep=slept.append)
    # 1, 2, 4, 4 (plafonné) — 4 backoffs pour 5 tentatives.
    assert slept == [1.0, 2.0, 4.0, 4.0]
