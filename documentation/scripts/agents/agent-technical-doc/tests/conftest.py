"""Configuration pytest : rend le package de l'agent importable sans installation.

Ajoute le dossier de l'agent (parent de ``docagent``) au ``sys.path`` afin que
``import docagent...`` fonctionne quel que soit le répertoire d'exécution.
"""
import os
import sys

AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT_ROOT not in sys.path:
    sys.path.insert(0, AGENT_ROOT)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "e2e: test de bout en bout nécessitant une stack déployée (skippé sans env).",
    )
