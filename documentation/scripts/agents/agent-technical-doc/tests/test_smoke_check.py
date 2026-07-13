"""Garde-fou du helper smoke (Phase 2) : classification du commentaire terminal."""
from e2e import smoke_check


def test_classify_none_when_no_terminal_comment():
    outcome, body = smoke_check._classify_comments(
        [{"body": "un commentaire quelconque"}, {"body": "👀"}]
    )
    assert outcome is None
    assert body == ""


def test_classify_success():
    outcome, body = smoke_check._classify_comments(
        [{"body": "## 📚 Documentation technique générée\n\nRésumé…"}]
    )
    assert outcome == "success"
    assert "générée" in body


def test_classify_failure():
    outcome, _ = smoke_check._classify_comments(
        [{"body": "## ⚠️ Documentation technique — échec\n\nRaison…"}]
    )
    assert outcome == "failure"


def test_classify_fork():
    outcome, _ = smoke_check._classify_comments(
        [{"body": "## ℹ️ Documentation technique non générée\n\nFork…"}]
    )
    assert outcome == "fork"


def test_classify_takes_most_recent():
    # Le plus récent (dernier de la liste) prime.
    outcome, _ = smoke_check._classify_comments([
        {"body": "## ⚠️ Documentation technique — échec"},
        {"body": "## 📚 Documentation technique générée"},
    ])
    assert outcome == "success"


def test_classify_handles_non_dict_and_empty():
    assert smoke_check._classify_comments([]) == (None, "")
    assert smoke_check._classify_comments([None, "x"]) == (None, "")
