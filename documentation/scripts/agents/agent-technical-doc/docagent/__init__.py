"""docagent — logique métier de l'agent de documentation technique.

Les modules de ce package sont conçus pour être testables sans dépendances
lourdes : les imports de ``boto3`` et de ``strands`` sont différés à l'intérieur
des fonctions qui en ont besoin, de sorte que la logique pure (lecture bornée,
sélection, génération markdown/drawio, garde-fous de commit) reste importable et
unit-testable dans un environnement minimal.
"""

__all__ = [
    "config",
    "correlation",
    "repo_reader",
    "selection",
    "drawio",
    "doc_builder",
    "github_client",
    "secrets",
]
