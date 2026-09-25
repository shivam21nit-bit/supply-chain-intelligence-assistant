"""Data layer for the supply chain graph, stored in Neo4j AuraDB.

Uses Neo4j's HTTP Query API (plain HTTPS, port 443) rather than the
official Bolt driver (port 7687) — the Bolt protocol is blocked by this
machine's corporate VPN, but standard HTTPS is not, since the driver's
own SSL handshake failed identically on multiple networks while the
Aura web console (also plain HTTPS) worked fine. This is a workaround
for a network constraint, not a downgrade in what we can do with Cypher.

All queries are parameterized — never string-format user input directly
into a Cypher statement (the one exception is node type, which is a
label and Cypher can't parameterize labels; that's validated against a
fixed whitelist before use, precisely to avoid injection there).
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

NODE_TYPES = {"Supplier", "Warehouse", "Destination"}


def _endpoint() -> str:
    uri = os.environ["NEO4J_URI"]
    hostname = uri.split("neo4j+s://")[1]
    database = os.environ["NEO4J_DATABASE"]
    return f"https://{hostname}/db/{database}/query/v2"


def _auth() -> tuple[str, str]:
    return (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])


def run_query(statement: str, parameters: dict | None = None) -> list[dict]:
    try:
        response = requests.post(
            _endpoint(),
            auth=_auth(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"statement": statement, "parameters": parameters or {}},
            timeout=20,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Neo4j request failed ({e.__class__.__name__}): {e}")

    if response.status_code not in (200, 202):
        raise RuntimeError(f"Neo4j query failed ({response.status_code}): {response.text[:300]}")

    body = response.json()
    if "errors" in body and body["errors"]:
        raise RuntimeError(f"Neo4j query error: {body['errors']}")

    data = body["data"]
    fields = data["fields"]
    return [dict(zip(fields, row)) for row in data["values"]]


def ensure_constraint() -> None:
    run_query(
        "CREATE CONSTRAINT node_name_unique IF NOT EXISTS "
        "FOR (n:Node) REQUIRE n.name IS UNIQUE"
    )


def add_node(node_type: str, name: str, country: str, items: list[str]) -> None:
    if node_type not in NODE_TYPES:
        raise ValueError(f"node_type must be one of {NODE_TYPES}, got '{node_type}'")
    run_query(
        f"CREATE (n:Node:{node_type} {{name: $name, country: $country, items: $items}})",
        {"name": name, "country": country, "items": items},
    )


def get_all_nodes() -> list[dict]:
    rows = run_query(
        "MATCH (n:Node) RETURN n.name AS name, labels(n) AS labels, "
        "n.country AS country, n.items AS items ORDER BY n.name"
    )
    for row in rows:
        row["type"] = next(l for l in row["labels"] if l != "Node")
    return rows


def add_edge(from_name: str, to_name: str, item: str, mode: str, notes: str) -> None:
    existing = run_query(
        "MATCH (a:Node {name: $from_name}), (b:Node {name: $to_name}) "
        "RETURN a.name AS a, b.name AS b",
        {"from_name": from_name, "to_name": to_name},
    )
    if not existing:
        raise ValueError(f"Could not find both nodes: '{from_name}' and '{to_name}'")

    run_query(
        "MATCH (a:Node {name: $from_name}), (b:Node {name: $to_name}) "
        "CREATE (a)-[:SUPPLIES {item: $item, mode: $mode, notes: $notes}]->(b)",
        {"from_name": from_name, "to_name": to_name, "item": item, "mode": mode, "notes": notes},
    )


def get_all_edges() -> list[dict]:
    return run_query(
        "MATCH (a:Node)-[r:SUPPLIES]->(b:Node) "
        "RETURN a.name AS from_name, b.name AS to_name, r.item AS item, "
        "r.mode AS mode, r.notes AS notes ORDER BY a.name"
    )


def delete_node(name: str) -> int:
    """Deletes a node and any routes attached to it. Returns how many
    routes were removed along with it, so the caller can report it
    explicitly rather than silently orphaning references."""
    result = run_query(
        "MATCH (n:Node {name: $name}) OPTIONAL MATCH (n)-[r]-() "
        "RETURN count(r) AS route_count",
        {"name": name},
    )
    route_count = result[0]["route_count"] if result else 0

    run_query("MATCH (n:Node {name: $name}) DETACH DELETE n", {"name": name})
    return route_count


def delete_edge(from_name: str, to_name: str) -> bool:
    existing = run_query(
        "MATCH (a:Node {name: $from_name})-[r:SUPPLIES]->(b:Node {name: $to_name}) "
        "RETURN count(r) AS c",
        {"from_name": from_name, "to_name": to_name},
    )
    if not existing or existing[0]["c"] == 0:
        return False

    run_query(
        "MATCH (a:Node {name: $from_name})-[r:SUPPLIES]->(b:Node {name: $to_name}) DELETE r",
        {"from_name": from_name, "to_name": to_name},
    )
    return True
