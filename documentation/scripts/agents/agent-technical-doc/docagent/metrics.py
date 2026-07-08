"""Émission de métriques via le format EMF (Embedded Metric Format).

Les métriques sont écrites sur stdout au format EMF : CloudWatch les extrait
automatiquement des logs applicatifs du runtime, sans appel PutMetricData ni
permission supplémentaire. Chaque émission porte le ``correlation_id`` pour
relier métrique et logs d'un même run.
"""
from __future__ import annotations

import json
import sys
import time

NAMESPACE = "AgentTechnicalDoc"
AGENT = "agent-technical-doc"


def emit_run(outcome: str, *, duration_ms: float, correlation_id: str,
             files: int = 0, out=None) -> dict:
    """Émet une métrique de run (Runs=1) avec dimension ``Outcome`` + durée.

    ``outcome`` ∈ {complete, failed, skipped_fork, skipped_duplicate, invalid_request}.
    Retourne le document EMF émis (utile pour les tests).
    """
    doc = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [["Agent", "Outcome"]],
                    "Metrics": [
                        {"Name": "Runs", "Unit": "Count"},
                        {"Name": "DurationMs", "Unit": "Milliseconds"},
                        {"Name": "FilesCommitted", "Unit": "Count"},
                    ],
                }
            ],
        },
        "Agent": AGENT,
        "Outcome": outcome,
        "Runs": 1,
        "DurationMs": round(float(duration_ms), 1),
        "FilesCommitted": int(files),
        "correlation_id": correlation_id,
    }
    line = json.dumps(doc)
    (out or sys.stdout).write(line + "\n")
    return doc
