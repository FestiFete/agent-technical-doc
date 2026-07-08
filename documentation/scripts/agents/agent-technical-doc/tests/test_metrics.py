"""Task 11 — émission de métriques EMF."""
import io
import json

from docagent import metrics


def test_emit_run_emf_shape():
    buf = io.StringIO()
    doc = metrics.emit_run("complete", duration_ms=1234.5, correlation_id="c1",
                           files=6, out=buf)
    # document bien formé + écrit sur la sortie
    line = buf.getvalue().strip()
    parsed = json.loads(line)
    assert parsed["Outcome"] == "complete"
    assert parsed["Runs"] == 1
    assert parsed["FilesCommitted"] == 6
    assert parsed["correlation_id"] == "c1"
    # structure EMF reconnue par CloudWatch
    cw = parsed["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == "AgentTechnicalDoc"
    names = {m["Name"] for m in cw["Metrics"]}
    assert {"Runs", "DurationMs", "FilesCommitted"} <= names
    assert doc["Outcome"] == "complete"
