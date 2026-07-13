"""Task 7 — orchestration bout-en-bout avec dépendances injectées (sans réseau)."""
from docagent.orchestrator import OrchestratorDeps, run_documentation
from docagent.payload import parse_request


def _payload(**over):
    base = {
        "repo_full_name": "acme/widget", "pr_number": 42,
        "head_sha": "abcdef1234567890", "head_ref": "feature/x",
        "base_repo_full_name": "acme/widget", "comment_id": 7,
        "is_fork": False, "correlation_id": "corr-1",
    }
    base.update(over)
    return base


class FakeReader:
    def list_tree(self):
        return ["README.md", "package.json", "src/index.js", "src/models/user.js"]

    def read_file(self, path):
        return {"README.md": "# Widget\nGère des widgets.",
                "package.json": '{"name":"widget"}'}.get(path, "code")


class FakeClient:
    def __init__(self):
        self.reactions = []
        self.comments = []
        self.commits = []
        self._seq = 0

    # lecture / restitution
    def add_reaction(self, repo, comment_id, content="eyes"):
        self.reactions.append((repo, comment_id, content))
        return {}

    def get_pull_request(self, repo, pr_number):
        return {
            "head": {"sha": "RESOLVEDSHA", "ref": "feature/x",
                     "repo": {"full_name": "acme/widget"}},
            "base": {"repo": {"full_name": "acme/widget"}},
        }

    def post_issue_comment(self, repo, issue, body):
        self.comments.append({"repo": repo, "issue": issue, "body": body})
        return {}

    # git data api
    def get_ref(self, repo, ref):
        return {"object": {"sha": "TIP"}}

    def get_commit(self, repo, sha):
        return {"tree": {"sha": "BASE"}}

    def create_blob(self, repo, content, encoding="utf-8"):
        self._seq += 1
        return {"sha": f"b{self._seq}"}

    def create_tree(self, repo, base_tree, tree):
        self._tree = tree
        return {"sha": "T"}

    def create_commit(self, repo, message, tree_sha, parent_sha):
        self.commits.append(message)
        return {"sha": "COMMITSHA"}

    def update_ref(self, repo, ref, sha, force=False):
        self.ref_update = {"ref": ref, "sha": sha, "force": force}
        return {}


def _analysis(_ctx):
    return {
        "name": "Widget", "purpose": "Gère des widgets", "summary": "Projet Node.js.",
        "stack": [{"name": "Node.js", "kind": "runtime", "role": "backend"}],
        "components": [{"name": "API", "responsibility": "REST"}],
        "use_cases": ["Créer un widget"],
        "missing": "",
        "diagrams": [
            {"path": "diagrams/c4-context.drawio",
             "spec": {"type": "c4", "title": "Contexte",
                      "nodes": [{"id": "u", "label": "User", "kind": "person"},
                                {"id": "s", "label": "Widget", "kind": "system"}],
                      "edges": [{"from": "u", "to": "s", "label": "utilise"}]}},
        ],
    }


def _deps(client, analyze=_analysis, claim=lambda k, c: True, release=None):
    kwargs = dict(
        get_token=lambda *_a: "ghp_fake",
        make_client=lambda token: client,
        fetch_repo=lambda c, repo, ref, wd: FakeReader(),
        analyze=analyze,
        claim_idempotency=claim,
    )
    if release is not None:
        kwargs["release_idempotency"] = release
    return OrchestratorDeps(**kwargs)


def test_nominal_run_commits_and_comments(tmp_path):
    client = FakeClient()
    req = parse_request(_payload(), None)
    resp = run_documentation(req, session_id="s1", deps=_deps(client), workdir=str(tmp_path))
    r = resp["result"]
    assert r["status"] == "complete"
    assert r["commit_sha"] == "COMMITSHA"
    # accusé de réception posé, un commentaire de succès posté, un seul commit.
    assert client.reactions and client.reactions[0][2] == "eyes"
    assert len(client.commits) == 1
    assert len(client.comments) == 1
    assert "Documentation technique générée" in client.comments[0]["body"]
    # les fichiers canoniques + le schéma sont présents et confinés.
    assert any(f.endswith("overview.md") for f in r["files"])
    assert any(f.endswith("c4-context.drawio") for f in r["files"])
    assert all(f.startswith("docs/agent/") for f in r["files"])


def test_fork_is_skipped_without_network():
    client = FakeClient()
    req = parse_request(_payload(is_fork=True), None)
    resp = run_documentation(req, session_id="s1", deps=_deps(client))
    assert resp["result"]["status"] == "skipped_fork"
    assert client.commits == []
    assert client.comments == []  # pas de client sollicité


def test_failure_posts_terminal_comment(tmp_path):
    client = FakeClient()

    def boom(_ctx):
        raise RuntimeError("analyse impossible")

    req = parse_request(_payload(), None)
    resp = run_documentation(req, session_id="s1", deps=_deps(client, analyze=boom),
                             workdir=str(tmp_path))
    assert resp["result"]["status"] == "failed"
    # commentaire terminal d'échec posté malgré l'erreur.
    assert len(client.comments) == 1
    assert "échec" in client.comments[0]["body"].lower()
    assert client.commits == []


def test_secret_never_in_error_response(tmp_path):
    client = FakeClient()

    def boom(_ctx):
        raise RuntimeError("token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123 leaked")

    req = parse_request(_payload(), None)
    resp = run_documentation(req, session_id="s1", deps=_deps(client, analyze=boom),
                             workdir=str(tmp_path))
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in resp["result"]["error"]


def test_resolves_pr_details_when_payload_minimal(tmp_path):
    """Payload sans head_sha/head_ref : l'orchestrateur résout via get_pull_request."""
    client = FakeClient()
    # payload minimal (comme produit par la Lambda webhook, sans détails PR)
    req = parse_request({"repo_full_name": "acme/widget", "pr_number": 42,
                         "comment_id": 7, "correlation_id": "c1"}, None)
    assert not req.is_resolved
    resp = run_documentation(req, session_id="s1", deps=_deps(client), workdir=str(tmp_path))
    assert resp["result"]["status"] == "complete"
    # le commit s'est fait sur la branche résolue.
    assert client.ref_update["ref"] == "heads/feature/x"


def test_resolved_fork_is_skipped_with_comment(tmp_path):
    """PR dont le head vient d'un fork : refus + commentaire (après résolution)."""
    client = FakeClient()

    def _fork_pr(repo, pr_number):
        return {
            "head": {"sha": "S", "ref": "f", "repo": {"full_name": "attacker/widget"}},
            "base": {"repo": {"full_name": "acme/widget"}},
        }

    client.get_pull_request = _fork_pr
    req = parse_request({"repo_full_name": "acme/widget", "pr_number": 42,
                         "comment_id": 7}, None)
    resp = run_documentation(req, session_id="s1", deps=_deps(client), workdir=str(tmp_path))
    assert resp["result"]["status"] == "skipped_fork"
    assert client.commits == []
    assert len(client.comments) == 1
    assert "fork" in client.comments[0]["body"].lower()


def test_duplicate_claim_skips_run(tmp_path):
    """Si l'idempotence indique un doublon (claim False), aucun commit."""
    client = FakeClient()
    req = parse_request(_payload(), None)
    resp = run_documentation(req, session_id="s1",
                             deps=_deps(client, claim=lambda k, c: False),
                             workdir=str(tmp_path))
    assert resp["result"]["status"] == "skipped_duplicate"
    assert client.commits == []


def test_claim_uses_repo_pr_sha_key(tmp_path):
    """La clé d'idempotence passée au claim est bien repo#pr#sha (résolu)."""
    client = FakeClient()
    seen = {}

    def _claim(key, corr):
        seen["key"] = key
        return True

    req = parse_request({"repo_full_name": "acme/widget", "pr_number": 42,
                         "comment_id": 7}, None)
    run_documentation(req, session_id="s1", deps=_deps(client, claim=_claim),
                      workdir=str(tmp_path))
    assert seen["key"] == "acme/widget#42#RESOLVEDSHA"


def test_failure_releases_idempotency(tmp_path):
    """Échec après revendication : la clé d'idempotence est relâchée (re-run possible)."""
    client = FakeClient()
    released = []

    def boom(_ctx):
        raise RuntimeError("analyse impossible")

    req = parse_request(_payload(), None)
    resp = run_documentation(req, session_id="s1",
                             deps=_deps(client, analyze=boom, release=released.append),
                             workdir=str(tmp_path))
    assert resp["result"]["status"] == "failed"
    assert released == ["acme/widget#42#abcdef1234567890"]


def test_success_keeps_idempotency(tmp_path):
    """Succès : la clé persiste (déduplication maintenue) — pas de relâche."""
    client = FakeClient()
    released = []
    req = parse_request(_payload(), None)
    resp = run_documentation(req, session_id="s1",
                             deps=_deps(client, release=released.append),
                             workdir=str(tmp_path))
    assert resp["result"]["status"] == "complete"
    assert released == []


def test_duplicate_does_not_release(tmp_path):
    """Doublon (claim False) : on n'a rien revendiqué, donc rien à relâcher."""
    client = FakeClient()
    released = []
    req = parse_request(_payload(), None)
    resp = run_documentation(req, session_id="s1",
                             deps=_deps(client, claim=lambda k, c: False, release=released.append),
                             workdir=str(tmp_path))
    assert resp["result"]["status"] == "skipped_duplicate"
    assert released == []
