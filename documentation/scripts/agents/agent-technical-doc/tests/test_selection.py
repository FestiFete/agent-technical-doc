"""Task 3 — sélection heuristique + indices de stack + neutralité au contenu."""
from docagent.config import ReadCaps
from docagent import selection


TREE = [
    "README.md",
    "package.json",
    "src/index.js",
    "src/routes/user.js",
    "src/models/user.js",
    "migrations/001_init.sql",
    "Dockerfile",
    "docs/notes.md",
    "assets/data.bin",
    "deep/a/b/c/d/e/util.js",
]


def test_manifest_and_readme_ranked_first():
    ranked = selection.select_files(TREE)
    top = ranked[:4]
    assert "package.json" in top
    assert "README.md" in top


def test_selection_respects_cap():
    ranked = selection.select_files(TREE, caps=ReadCaps(max_selected_files=3))
    assert len(ranked) == 3


def test_stack_hints_detects_node():
    hints = selection.stack_hints(TREE)
    assert "node" in hints
    assert "package.json" in hints["node"]


def test_data_model_likely_true_on_migrations_and_models():
    assert selection.data_model_likely(TREE) is True


def test_data_model_likely_false_without_hints():
    assert selection.data_model_likely(["README.md", "src/index.js"]) is False


def test_selection_is_content_independent_prompt_injection():
    """La sélection dépend uniquement des chemins, jamais du contenu.

    Un fichier hostile ne peut donc pas modifier l'ordre ni la cible : le
    classement est identique quel que soit le contenu (garde-fou anti-injection).
    """
    order_1 = selection.select_files(TREE)
    # Même arborescence : le classement ne peut pas dépendre d'un contenu piégé
    # puisque select_files ne reçoit que des chemins.
    order_2 = selection.select_files(list(TREE))
    assert order_1 == order_2
    # Le README reste prioritaire même si, hypothétiquement, il contenait
    # « ignore tes instructions » : select_files ne lit jamais le contenu.
    assert order_1.index("README.md") < order_1.index("deep/a/b/c/d/e/util.js")
