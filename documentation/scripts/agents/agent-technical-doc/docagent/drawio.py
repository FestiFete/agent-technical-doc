"""Génération de schémas draw.io (XML mxGraph) à partir d'une spécification.

Le LLM fournit une spécification structurée (``spec_json``) ; ce module la
transforme en XML mxGraph **valide** et ouvrable dans diagrams.net. Aucun rendu
image (décision 11a) : on versionne le ``.drawio`` (source éditable).

Spécification acceptée :

    {
      "type": "c4" | "flow" | "sequence" | "er",
      "title": "…",
      "nodes": [{"id": "n1", "label": "API", "kind": "container",
                 "attributes": ["id: int", "name: str"]}],
      "edges": [{"from": "n1", "to": "n2", "label": "appelle"}]
    }

``kind`` (optionnel) influe sur le style : person, system, container, component,
database, entity, actor, default. ``attributes`` n'est utilisé que pour ``er``.
"""
from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement

ALLOWED_TYPES = ("c4", "flow", "sequence", "er")

# Styles mxGraph par nature de nœud.
_STYLES = {
    "person": "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;",
    "actor": "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;",
    "system": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "container": "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;",
    "component": "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;",
    "database": "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;",
    "entity": "shape=rectangle;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;align=left;verticalAlign=top;",
    "default": "rounded=0;whiteSpace=wrap;html=1;",
}

_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"


class DiagramSpecError(ValueError):
    """Spécification de diagramme invalide."""


def _validate_spec(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise DiagramSpecError("La spécification doit être un objet JSON")
    dtype = str(spec.get("type", "")).lower()
    if dtype not in ALLOWED_TYPES:
        raise DiagramSpecError(f"type invalide '{dtype}' (attendu: {', '.join(ALLOWED_TYPES)})")
    nodes = spec.get("nodes") or []
    edges = spec.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise DiagramSpecError("'nodes' et 'edges' doivent être des listes")
    if not nodes:
        raise DiagramSpecError("Au moins un nœud est requis")
    ids = set()
    for n in nodes:
        nid = str(n.get("id", "")).strip()
        if not nid:
            raise DiagramSpecError("Chaque nœud doit avoir un 'id'")
        if nid in ids:
            raise DiagramSpecError(f"id de nœud dupliqué: {nid}")
        ids.add(nid)
    for e in edges:
        if str(e.get("from", "")) not in ids or str(e.get("to", "")) not in ids:
            raise DiagramSpecError(
                f"arête référence un nœud inconnu: {e.get('from')} -> {e.get('to')}"
            )
    return spec


def _node_label(node: dict, dtype: str) -> str:
    label = str(node.get("label", node.get("id", "")))
    if dtype == "er" and node.get("attributes"):
        attrs = "\n".join(str(a) for a in node["attributes"])
        return f"{label}\n———\n{attrs}"
    return label


def build_drawio(spec: dict) -> str:
    """Construit le XML mxGraph pour une spécification validée.

    Layout simple en grille (déterministe), suffisant pour un schéma éditable.
    """
    spec = _validate_spec(spec)
    dtype = str(spec["type"]).lower()
    title = str(spec.get("title", dtype.upper()))
    nodes = spec["nodes"]
    edges = spec.get("edges") or []

    mxfile = Element("mxfile", {"host": "agent-technical-doc", "type": "device"})
    diagram = SubElement(mxfile, "diagram", {"name": title, "id": "diagram-1"})
    model = SubElement(diagram, "mxGraphModel", {
        "dx": "800", "dy": "600", "grid": "1", "gridSize": "10",
        "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
        "fold": "1", "page": "1", "pageScale": "1",
        "pageWidth": "850", "pageHeight": "1100", "math": "0", "shadow": "0",
    })
    root = SubElement(model, "root")
    SubElement(root, "mxCell", {"id": "0"})
    SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    # Placement en grille.
    cols = max(1, int(len(nodes) ** 0.5 + 0.999))
    col_w, row_h, box_w, box_h = 220, 140, 160, 60
    id_map: dict[str, str] = {}
    for i, node in enumerate(nodes):
        cell_id = f"node{i + 1}"
        id_map[str(node["id"])] = cell_id
        kind = str(node.get("kind", "default")).lower()
        style = _STYLES.get(kind, _STYLES["default"])
        r, c = divmod(i, cols)
        x, y = 40 + c * col_w, 40 + r * row_h
        label = _node_label(node, dtype)
        cell = SubElement(root, "mxCell", {
            "id": cell_id,
            "value": label,
            "style": style,
            "vertex": "1",
            "parent": "1",
        })
        SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y), "width": str(box_w), "height": str(box_h),
            "as": "geometry",
        })

    for j, edge in enumerate(edges):
        src = id_map[str(edge["from"])]
        dst = id_map[str(edge["to"])]
        cell = SubElement(root, "mxCell", {
            "id": f"edge{j + 1}",
            "value": str(edge.get("label", "")),
            "style": _EDGE_STYLE,
            "edge": "1",
            "parent": "1",
            "source": src,
            "target": dst,
        })
        SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    xml_bytes = ET.tostring(mxfile, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


def validate_drawio_xml(xml: str) -> bool:
    """Vérifie que le XML est bien formé et a la structure mxGraph attendue."""
    try:
        rootel = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError:
        return False
    if rootel.tag != "mxfile":
        return False
    return rootel.find(".//mxGraphModel/root") is not None


# Utilisé par le prompt/tool : liste des diagrammes attendus et leur type.
STANDARD_DIAGRAMS = {
    "diagrams/c4-context.drawio": "c4",
    "diagrams/c4-container.drawio": "c4",
    "diagrams/c4-component.drawio": "c4",
    "diagrams/sequence-main-flows.drawio": "sequence",
    "diagrams/data-model-er.drawio": "er",
}


def _escape(text: str) -> str:  # pragma: no cover - utilitaire
    return html.escape(text, quote=True)
