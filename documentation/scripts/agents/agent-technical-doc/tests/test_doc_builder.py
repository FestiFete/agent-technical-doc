"""Task 4 — génération Markdown + garde-fou de chemin partagé."""
import pytest

from docagent.doc_builder import DOC_FILES, DocumentSet, render_default_docs, render_index
from docagent.paths import PathNotAllowedError, normalize_output_path


# --- garde-fou de chemin (paths.py) -----------------------------------------
def test_normalize_prefixes_output_dir():
    assert normalize_output_path("overview.md") == "docs/agent/overview.md"


def test_normalize_keeps_existing_prefix():
    assert normalize_output_path("docs/agent/diagrams/x.drawio") == "docs/agent/diagrams/x.drawio"


def test_normalize_rejects_traversal():
    with pytest.raises(PathNotAllowedError):
        normalize_output_path("../../etc/passwd.md")


def test_normalize_rejects_escape_via_prefix():
    with pytest.raises(PathNotAllowedError):
        normalize_output_path("docs/agent/../../secrets.md")


def test_normalize_rejects_absolute():
    with pytest.raises(PathNotAllowedError):
        normalize_output_path("/etc/passwd.md")


def test_normalize_rejects_bad_extension():
    with pytest.raises(PathNotAllowedError):
        normalize_output_path("overview.txt")


# --- DocumentSet -------------------------------------------------------------
def test_document_set_validates_paths():
    ds = DocumentSet()
    ds.add("overview.md", "# hi")
    assert "docs/agent/overview.md" in ds.files
    with pytest.raises(PathNotAllowedError):
        ds.add("../evil.md", "x")


# --- rendu par défaut --------------------------------------------------------
def test_render_default_docs_has_canonical_files():
    docs = render_default_docs({
        "name": "Widget",
        "purpose": "Gère des widgets",
        "stack": [{"name": "Node.js", "kind": "runtime", "role": "backend"}],
        "components": [{"name": "API", "responsibility": "expose REST"}],
        "use_cases": ["Créer un widget"],
    }, diagrams=["docs/agent/diagrams/c4-context.drawio"])
    assert "README.md" in docs
    for f in DOC_FILES:
        assert f in docs
    assert "Gère des widgets" in docs["overview.md"]
    assert "Node.js" in docs["stack.md"]
    assert "c4-context.drawio" in docs["architecture.md"]


def test_render_default_docs_flags_missing_info():
    docs = render_default_docs({"name": "Empty"})
    assert "Non déterminé à partir du dépôt" in docs["overview.md"]


def test_render_index_lists_sections():
    idx = render_index("Widget", diagrams=["docs/agent/diagrams/sequence-main-flows.drawio"])
    assert "overview.md" in idx
    assert "sequence-main-flows.drawio" in idx
