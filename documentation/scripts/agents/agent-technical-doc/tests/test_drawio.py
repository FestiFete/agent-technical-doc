"""Task 5 — génération de schémas draw.io (XML mxGraph valide)."""
import xml.etree.ElementTree as ET

import pytest

from docagent.drawio import DiagramSpecError, build_drawio, validate_drawio_xml


def _c4_spec():
    return {
        "type": "c4",
        "title": "Contexte",
        "nodes": [
            {"id": "u", "label": "Utilisateur", "kind": "person"},
            {"id": "sys", "label": "Système", "kind": "system"},
            {"id": "ext", "label": "API externe", "kind": "system"},
        ],
        "edges": [
            {"from": "u", "to": "sys", "label": "utilise"},
            {"from": "sys", "to": "ext", "label": "appelle"},
        ],
    }


def test_build_drawio_is_wellformed_and_valid():
    xml = build_drawio(_c4_spec())
    assert validate_drawio_xml(xml)
    root = ET.fromstring(xml)
    assert root.tag == "mxfile"


def test_build_drawio_contains_nodes_and_edges():
    xml = build_drawio(_c4_spec())
    root = ET.fromstring(xml)
    cells = root.findall(".//mxGraphModel/root/mxCell")
    vertices = [c for c in cells if c.get("vertex") == "1"]
    edges = [c for c in cells if c.get("edge") == "1"]
    assert len(vertices) == 3
    assert len(edges) == 2
    labels = {c.get("value") for c in vertices}
    assert "Utilisateur" in labels


def test_er_includes_attributes():
    spec = {
        "type": "er",
        "title": "Modèle",
        "nodes": [{"id": "user", "label": "User", "kind": "entity",
                   "attributes": ["id: int", "email: str"]}],
        "edges": [],
    }
    xml = build_drawio(spec)
    assert "email: str" in xml
    assert validate_drawio_xml(xml)


def test_invalid_type_rejected():
    with pytest.raises(DiagramSpecError):
        build_drawio({"type": "mindmap", "nodes": [{"id": "a"}], "edges": []})


def test_edge_referencing_unknown_node_rejected():
    with pytest.raises(DiagramSpecError):
        build_drawio({"type": "flow", "nodes": [{"id": "a"}],
                      "edges": [{"from": "a", "to": "zzz"}]})


def test_empty_nodes_rejected():
    with pytest.raises(DiagramSpecError):
        build_drawio({"type": "c4", "nodes": [], "edges": []})


def test_duplicate_node_id_rejected():
    with pytest.raises(DiagramSpecError):
        build_drawio({"type": "c4", "nodes": [{"id": "a"}, {"id": "a"}], "edges": []})


def test_validate_rejects_garbage():
    assert validate_drawio_xml("<not-mxfile/>") is False
    assert validate_drawio_xml("pas du xml <<<") is False


def test_special_characters_are_escaped():
    spec = {"type": "flow", "title": "T",
            "nodes": [{"id": "a", "label": "A & <B>"}], "edges": []}
    xml = build_drawio(spec)
    # Doit rester bien formé malgré les caractères spéciaux.
    assert validate_drawio_xml(xml)
    assert ET.fromstring(xml).find(".//mxCell[@vertex='1']").get("value") == "A & <B>"
