"""Data layer for the network optimizer — a real SQLite database
(Python's built-in `sqlite3`, zero install, zero signup), not the Neo4j
graph from supply_chain_graph/. That graph models a small hand-built
network of named nodes/routes; this models a much larger, tabular,
time-indexed network (item x location x week), which fits a relational
table far better than a property graph. The two stores are intentionally
separate — this never touches supply_chain_graph's data.
"""

import os
import sqlite3

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "network.db")

REQUIRED_LANE_COLUMNS = [
    "lane_id", "from_location", "to_location", "item",
    "cost_per_unit", "lead_time_weeks", "capacity_per_week",
]
REQUIRED_DEMAND_COLUMNS = ["location", "item", "week", "demand_qty"]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lanes (
            lane_id TEXT, from_location TEXT, to_location TEXT, item TEXT,
            cost_per_unit REAL, lead_time_weeks INTEGER, capacity_per_week REAL,
            PRIMARY KEY (lane_id, item)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS demand (
            location TEXT, item TEXT, week INTEGER, demand_qty REAL,
            PRIMARY KEY (location, item, week)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS starting_inventory (
            location TEXT, item TEXT, qty REAL,
            PRIMARY KEY (location, item)
        )
    """)
    return conn


def _validate_columns(df: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing required column(s): {', '.join(missing)}")


def load_lanes_df(df: pd.DataFrame) -> int:
    """Bulk upsert lanes from a DataFrame (e.g. an uploaded CSV). Raises
    ValueError with the exact missing columns rather than silently
    importing a partial/wrong schema. Returns the number of rows loaded."""
    _validate_columns(df, REQUIRED_LANE_COLUMNS, "Lanes file")
    with _connect() as conn:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO lanes VALUES (?,?,?,?,?,?,?)",
                (
                    str(row["lane_id"]), str(row["from_location"]), str(row["to_location"]),
                    str(row["item"]), float(row["cost_per_unit"]), int(row["lead_time_weeks"]),
                    float(row["capacity_per_week"]),
                ),
            )
    return len(df)


def load_demand_df(df: pd.DataFrame) -> int:
    _validate_columns(df, REQUIRED_DEMAND_COLUMNS, "Demand file")
    with _connect() as conn:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO demand VALUES (?,?,?,?)",
                (str(row["location"]), str(row["item"]), int(row["week"]), float(row["demand_qty"])),
            )
    return len(df)


def add_lane(lane_id: str, from_location: str, to_location: str, item: str,
             cost_per_unit: float, lead_time_weeks: int, capacity_per_week: float) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lanes VALUES (?,?,?,?,?,?,?)",
            (lane_id, from_location, to_location, item, cost_per_unit, lead_time_weeks, capacity_per_week),
        )


def add_demand_row(location: str, item: str, week: int, demand_qty: float) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO demand VALUES (?,?,?,?)",
            (location, item, week, demand_qty),
        )


def set_starting_inventory(location: str, item: str, qty: float) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO starting_inventory VALUES (?,?,?)", (location, item, qty))


def get_all_lanes() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query("SELECT * FROM lanes", conn)


def get_all_demand() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query("SELECT * FROM demand", conn)


def get_starting_inventory() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query("SELECT * FROM starting_inventory", conn)


def clear_all() -> None:
    """Wipes all three tables — used by tests/verification, not exposed
    as a casual UI button (deleting a whole network shouldn't be one click)."""
    with _connect() as conn:
        conn.execute("DELETE FROM lanes")
        conn.execute("DELETE FROM demand")
        conn.execute("DELETE FROM starting_inventory")
