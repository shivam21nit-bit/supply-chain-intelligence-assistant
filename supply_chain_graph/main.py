"""Supply Chain Graph wizard — slice 3 of the Supply Chain Intelligence
Assistant. Stores your own suppliers, warehouses, and routes in Neo4j.

Usage:
    python main.py
"""

from graph_store import (
    NODE_TYPES,
    add_edge,
    add_node,
    delete_edge,
    delete_node,
    ensure_constraint,
    get_all_edges,
    get_all_nodes,
)

MODES = ["sea", "air", "road", "rail"]


def prompt_choice(label: str, options: list[str]) -> str:
    while True:
        print(f"\n{label}")
        for i, opt in enumerate(options, 1):
            print(f"  {i}) {opt}")
        raw = input("Choice: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("Invalid choice, try again.")


def add_node_flow():
    node_type = prompt_choice("What kind of node?", sorted(NODE_TYPES))
    name = input("Name (must be unique, e.g. 'Acme Foods - Vietnam Plant'): ").strip()
    country = input("Country (free text, e.g. Vietnam): ").strip()
    items_raw = input("Item(s) this node deals in, comma-separated: ").strip()
    items = [i.strip() for i in items_raw.split(",") if i.strip()]

    try:
        add_node(node_type, name, country, items)
    except RuntimeError as e:
        if "already exists" in str(e) or "ConstraintValidationFailed" in str(e):
            print(f"A node named '{name}' already exists — names must be unique.")
        else:
            print(f"Failed to add node: {e}")
        return
    print(f"Added {node_type} '{name}'.")


def add_edge_flow():
    nodes = get_all_nodes()
    if len(nodes) < 2:
        print("You need at least 2 nodes before adding a route. Add nodes first.")
        return

    names = [n["name"] for n in nodes]
    print("\nExisting nodes:")
    for i, n in enumerate(nodes, 1):
        print(f"  {i}) {n['name']} ({n['type']}, {n['country']})")

    from_name = prompt_choice("Route FROM which node?", names)
    to_name = prompt_choice("Route TO which node?", names)
    item = input("Item carried on this route: ").strip()
    mode = prompt_choice("Transport mode?", MODES)
    notes = input("Notes (optional, e.g. typical chokepoint): ").strip()

    try:
        add_edge(from_name, to_name, item, mode, notes)
    except ValueError as e:
        print(f"Failed to add route: {e}")
        return
    print(f"Added route: {from_name} -> {to_name} ({item}, {mode}).")


def view_flow():
    nodes = get_all_nodes()
    edges = get_all_edges()

    print(f"\n--- Your supply chain: {len(nodes)} nodes, {len(edges)} routes ---")
    for node_type in sorted(NODE_TYPES):
        matching = [n for n in nodes if n["type"] == node_type]
        if not matching:
            continue
        print(f"\n{node_type}s:")
        for n in matching:
            items_str = ", ".join(n["items"]) if n["items"] else "(no items listed)"
            print(f"  - {n['name']} [{n['country']}] — {items_str}")

    print("\nRoutes:")
    if not edges:
        print("  (none yet)")
    for e in edges:
        notes_str = f" — {e['notes']}" if e["notes"] else ""
        print(f"  - {e['from_name']} -> {e['to_name']} ({e['item']}, {e['mode']}){notes_str}")


def delete_node_flow():
    nodes = get_all_nodes()
    if not nodes:
        print("No nodes to delete.")
        return
    names = [n["name"] for n in nodes]
    name = prompt_choice("Delete which node?", names)
    confirm = input(f"Type 'yes' to confirm deleting '{name}' and any routes touching it: ").strip()
    if confirm.lower() != "yes":
        print("Cancelled.")
        return
    route_count = delete_node(name)
    print(f"Deleted '{name}' and {route_count} attached route(s).")


def delete_edge_flow():
    edges = get_all_edges()
    if not edges:
        print("No routes to delete.")
        return
    labels = [f"{e['from_name']} -> {e['to_name']} ({e['item']}, {e['mode']})" for e in edges]
    choice = prompt_choice("Delete which route?", labels)
    idx = labels.index(choice)
    e = edges[idx]
    deleted = delete_edge(e["from_name"], e["to_name"])
    print("Deleted." if deleted else "Route not found (already deleted?).")


def main():
    print("Connecting to your supply chain graph...")
    ensure_constraint()
    nodes = get_all_nodes()
    edges = get_all_edges()
    print(f"Connected. You currently have {len(nodes)} nodes and {len(edges)} routes.")

    actions = {
        "Add a node (supplier / warehouse / destination)": add_node_flow,
        "Add a route between two nodes": add_edge_flow,
        "View my supply chain": view_flow,
        "Delete a node": delete_node_flow,
        "Delete a route": delete_edge_flow,
        "Exit": None,
    }

    while True:
        choice = prompt_choice("What do you want to do?", list(actions.keys()))
        if choice == "Exit":
            print("Goodbye.")
            break
        actions[choice]()


if __name__ == "__main__":
    main()
