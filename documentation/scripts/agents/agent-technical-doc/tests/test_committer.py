"""Task 6 — commit unique contraint + garde-fous + commentaires."""
import pytest

from docagent import comments
from docagent.committer import CommitTargetError, commit_documents, validate_files


class FakeGitHub:
    """Client GitHub factice capturant les appels Git Data API."""

    def __init__(self):
        self.blobs = []
        self.trees = []
        self.commits = []
        self.updated_ref = None
        self._blob_seq = 0

    def get_ref(self, repo, ref):
        assert ref.startswith("heads/")
        return {"object": {"sha": "TIPSHA"}}

    def get_commit(self, repo, sha):
        return {"tree": {"sha": "BASETREE"}}

    def create_blob(self, repo, content, encoding="utf-8"):
        self._blob_seq += 1
        self.blobs.append({"content": content})
        return {"sha": f"blob{self._blob_seq}"}

    def create_tree(self, repo, base_tree, tree):
        self.trees.append({"base_tree": base_tree, "tree": tree})
        return {"sha": "NEWTREE"}

    def create_commit(self, repo, message, tree_sha, parent_sha):
        self.commits.append({"message": message, "tree": tree_sha, "parent": parent_sha})
        return {"sha": "NEWCOMMIT"}

    def update_ref(self, repo, ref, sha, force=False):
        self.updated_ref = {"ref": ref, "sha": sha, "force": force}
        return {"object": {"sha": sha}}


def _files():
    return {
        "overview.md": "# overview",
        "docs/agent/architecture.md": "# archi",
        "diagrams/c4-context.drawio": "<mxfile/>",
    }


def test_single_commit_with_all_files():
    gh = FakeGitHub()
    result = commit_documents(
        gh, repo_full_name="acme/widget", head_ref="feature/x",
        files=_files(), message="docs: update",
    )
    # Un seul commit, une seule mise à jour de ref.
    assert len(gh.commits) == 1
    assert gh.updated_ref["ref"] == "heads/feature/x"
    assert gh.updated_ref["force"] is False
    assert result["commit_sha"] == "NEWCOMMIT"
    # Tous les fichiers présents, préfixés docs/agent/.
    assert set(result["files"]) == {
        "docs/agent/overview.md",
        "docs/agent/architecture.md",
        "docs/agent/diagrams/c4-context.drawio",
    }
    assert len(gh.blobs) == 3


def test_commit_base_tree_and_parent_from_tip():
    gh = FakeGitHub()
    commit_documents(gh, repo_full_name="acme/widget", head_ref="main",
                     files={"overview.md": "x"}, message="m")
    assert gh.trees[0]["base_tree"] == "BASETREE"
    assert gh.commits[0]["parent"] == "TIPSHA"


def test_rejects_file_outside_output_dir():
    gh = FakeGitHub()
    with pytest.raises(CommitTargetError):
        commit_documents(gh, repo_full_name="acme/widget", head_ref="main",
                         files={"../../evil.md": "x"}, message="m")
    # Aucun appel réseau d'écriture ne doit avoir eu lieu.
    assert gh.commits == []
    assert gh.updated_ref is None


def test_rejects_empty_branch():
    gh = FakeGitHub()
    with pytest.raises(CommitTargetError):
        commit_documents(gh, repo_full_name="acme/widget", head_ref="",
                         files={"overview.md": "x"}, message="m")


def test_validate_files_rejects_bad_extension():
    with pytest.raises(CommitTargetError):
        validate_files({"overview.txt": "x"})


def test_validate_files_rejects_empty():
    with pytest.raises(CommitTargetError):
        validate_files({})


# --- commentaires ------------------------------------------------------------
def test_success_comment_lists_files():
    body = comments.success_comment(
        summary="Projet Node.js.", files=["docs/agent/overview.md"],
        commit_sha="abcdef1234", missing="",
    )
    assert "overview.md" in body
    assert "abcdef1" in body


def test_failure_comment_has_reason_and_corr():
    body = comments.failure_comment(reason="clone impossible", correlation_id="c1")
    assert "clone impossible" in body
    assert "c1" in body


def test_fork_comment():
    assert "fork" in comments.fork_comment().lower()
