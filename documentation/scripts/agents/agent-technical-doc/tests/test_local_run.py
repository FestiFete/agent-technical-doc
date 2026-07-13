"""Garde-fou du runner Phase 1 (`e2e/local_run.py`) : délégation lecture /
neutralisation écriture, et résolution de token depuis l'environnement."""
import pytest

from e2e import local_run


class _RealSpy:
    def __init__(self):
        self.reads = []

    def get_pull_request(self, repo, pr):
        self.reads.append("get_pull_request")
        return {"head": {"sha": "S", "ref": "b", "repo": {"full_name": repo}},
                "base": {"repo": {"full_name": repo}}}

    def download_tarball(self, repo, ref):
        self.reads.append("download_tarball")
        return b"TAR"

    def get_ref(self, repo, ref):
        self.reads.append("get_ref")
        return {"object": {"sha": "TIP"}}

    def get_commit(self, repo, sha):
        self.reads.append("get_commit")
        return {"tree": {"sha": "BASE"}}


def test_dryrun_delegates_reads():
    real = _RealSpy()
    c = local_run.DryRunClient(real)
    assert c.get_ref("r", "ref")["object"]["sha"] == "TIP"
    assert c.download_tarball("r", "x") == b"TAR"
    assert c.get_commit("r", "S")["tree"]["sha"] == "BASE"
    assert c.get_pull_request("r", 1)["head"]["sha"] == "S"
    assert real.reads == ["get_ref", "download_tarball", "get_commit", "get_pull_request"]


def test_dryrun_stubs_writes_without_touching_real():
    real = _RealSpy()
    c = local_run.DryRunClient(real)
    assert c.create_blob("r", "x")["sha"].startswith("dryrun-blob")
    assert c.create_tree("r", "base", [{"path": "a"}])["sha"] == "dryrun-tree"
    assert c.create_commit("r", "msg", "t", "parentsha1234")["sha"].startswith("DRYRUN")
    assert c.update_ref("r", "heads/b", "sha") == {}
    assert c.post_issue_comment("r", 1, "body") == {}
    assert c.add_reaction("r", 1, "eyes") == {}
    # Aucune écriture ne doit atteindre le vrai client.
    assert real.reads == []


def test_captured_files_reconstruction():
    c = local_run.DryRunClient(_RealSpy())
    b1 = c.create_blob("r", "contenu-A")["sha"]
    b2 = c.create_blob("r", "contenu-B")["sha"]
    c.create_tree("r", "base", [
        {"path": "docs/agent/a.md", "sha": b1},
        {"path": "docs/agent/b.md", "sha": b2},
    ])
    files = c.captured_files()
    assert files == {"docs/agent/a.md": "contenu-A", "docs/agent/b.md": "contenu-B"}


def test_resolve_token_pat(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_SECRET", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_local")
    assert local_run._resolve_local_token("acme/widget") == "ghp_local"


def test_resolve_token_missing_raises(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_SECRET", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        local_run._resolve_local_token("acme/widget")
