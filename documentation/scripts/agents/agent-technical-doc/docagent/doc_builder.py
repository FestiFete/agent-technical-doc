"""Assemblage des livrables de documentation (Markdown) et index.

- :class:`DocumentSet` accumule les fichiers produits en validant chaque chemin
  via :mod:`paths` (invariant de sécurité : tout sous ``docs/agent/``).
- :func:`render_default_docs` produit un jeu Markdown déterministe à partir d'une
  analyse structurée. Sert de gabarit/repli et rend la génération testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import DOC_OUTPUT_DIR
from .paths import normalize_output_path

# Fichiers Markdown canoniques (relatifs à DOC_OUTPUT_DIR).
DOC_FILES = ("overview.md", "stack.md", "architecture.md", "functional.md")


@dataclass
class DocumentSet:
    """Collection de fichiers de documentation, validés à l'ajout."""

    output_dir: str = DOC_OUTPUT_DIR
    files: dict[str, str] = field(default_factory=dict)

    def add(self, path: str, content: str) -> str:
        """Ajoute/écrase un fichier. Retourne le chemin normalisé validé."""
        normalized = normalize_output_path(path, output_dir=self.output_dir)
        self.files[normalized] = content
        return normalized

    def paths(self) -> list[str]:
        return sorted(self.files.keys())

    def __len__(self) -> int:
        return len(self.files)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_Non déterminé à partir du dépôt._"
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return f"{head}\n{sep}\n{body}"


def _section(value, fallback: str = "_Non déterminé à partir du dépôt._") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def render_default_docs(analysis: dict, *, diagrams: list[str] | None = None) -> dict[str, str]:
    """Rend le jeu Markdown canonique à partir d'une analyse structurée.

    ``analysis`` (tous champs optionnels) :
      name, purpose, audience, stack (list[{name, kind, role}]),
      architecture_style, components (list[{name, responsibility}]),
      data_flows (str), external_deps (list[str]),
      use_cases (list[str]), notes (str).
    """
    analysis = analysis or {}
    name = _section(analysis.get("name"), "Projet")
    diagrams = diagrams or []

    overview = f"""# {name} — Vue d'ensemble

## Finalité

{_section(analysis.get("purpose"))}

## Publics visés

{_section(analysis.get("audience"))}
"""

    stack_rows = [
        [s.get("name", ""), s.get("kind", ""), s.get("role", "")]
        for s in (analysis.get("stack") or [])
    ]
    stack = f"""# Stack technique

{_table(["Élément", "Type", "Rôle"], stack_rows)}

## Dépendances externes

{_bullets(analysis.get("external_deps"))}
"""

    comp_rows = [
        [c.get("name", ""), c.get("responsibility", "")]
        for c in (analysis.get("components") or [])
    ]
    diagram_links = "\n".join(f"- [`{d}`]({_rel_to_docs(d)})" for d in diagrams) or \
        "_Aucun schéma généré._"
    architecture = f"""# Architecture

## Style d'architecture

{_section(analysis.get("architecture_style"))}

## Composants principaux

{_table(["Composant", "Responsabilité"], comp_rows)}

## Flux de données

{_section(analysis.get("data_flows"))}

## Schémas

{diagram_links}
"""

    functional = f"""# Vue fonctionnelle

## Cas d'usage principaux

{_bullets(analysis.get("use_cases"))}

## Notes

{_section(analysis.get("notes"), "—")}
"""

    readme = render_index(name, diagrams=diagrams)

    return {
        "README.md": readme,
        "overview.md": overview,
        "stack.md": stack,
        "architecture.md": architecture,
        "functional.md": functional,
    }


def _bullets(items) -> str:
    items = items or []
    if not items:
        return "_Non déterminé à partir du dépôt._"
    return "\n".join(f"- {str(i).strip()}" for i in items if str(i).strip())


def _rel_to_docs(diagram_path: str) -> str:
    """Lien relatif depuis un fichier à la racine de docs/agent vers un schéma."""
    p = diagram_path.replace("\\", "/")
    prefix = DOC_OUTPUT_DIR + "/"
    if p.startswith(prefix):
        return p[len(prefix):]
    return p


def assemble_document_set(analysis: dict, *, output_dir: str = DOC_OUTPUT_DIR) -> tuple:
    """Construit le :class:`DocumentSet` complet (Markdown + schémas) depuis l'analyse.

    ``analysis["diagrams"]`` : liste de ``{"path", "spec"}``. Chaque schéma est
    rendu en XML mxGraph validé ; les schémas invalides sont ignorés et signalés.

    Retourne ``(DocumentSet, diagram_paths, warnings)``.
    """
    from .drawio import DiagramSpecError, build_drawio  # import local (pas de cycle au chargement)

    analysis = analysis or {}
    ds = DocumentSet(output_dir=output_dir)
    diagram_paths: list[str] = []
    warnings: list[str] = []

    for entry in (analysis.get("diagrams") or []):
        path = entry.get("path", "")
        spec = entry.get("spec", {})
        try:
            xml = build_drawio(spec)
            norm = ds.add(path, xml)
            diagram_paths.append(norm)
        except (DiagramSpecError, ValueError) as exc:
            name = path.rsplit("/", 1)[-1] or path
            warnings.append(
                f"Diagramme `{name}` non généré (spécification incomplète : {exc})."
            )

    docs = render_default_docs(analysis, diagrams=diagram_paths)
    for rel, content in docs.items():
        ds.add(rel, content)

    return ds, diagram_paths, warnings


def render_index(name: str, *, diagrams: list[str] | None = None) -> str:
    diagrams = diagrams or []
    diagram_lines = "\n".join(f"- [`{_rel_to_docs(d)}`]({_rel_to_docs(d)})" for d in diagrams)
    diagram_block = diagram_lines or "_Aucun schéma généré._"
    return f"""# Documentation technique — {name}

> Documentation générée automatiquement par `agent-technical-doc`.

## Sommaire

- [Vue d'ensemble](overview.md)
- [Stack technique](stack.md)
- [Architecture](architecture.md)
- [Vue fonctionnelle](functional.md)

## Schémas (`diagrams/`)

{diagram_block}
"""
