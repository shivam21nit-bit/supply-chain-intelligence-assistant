"""Solves the multi-period transportation problem: given lanes (cost,
lead time, capacity) and weekly demand per location/item, find the
cost-minimizing shipment plan, allowing unmet demand at a penalty cost
rather than treating an under-supplied network as infeasible.

Uses Google OR-Tools' GLOP solver (free, open-source, actively developed
by Google) via its `pywraplp` linear-programming interface. GLOP is the
right OR-Tools backend here specifically because this model has no
integer/MIP variables (see "explicitly out of scope" in the plan/README —
minimum order quantities, fixed lane-activation costs, etc. would need
OR-Tools' CP-SAT solver instead, a real switch, not a flag, if added later).

Deliberate simplifications (see the plan/README for why): inventory
carries forward between weeks with no holding cost; capacity is flat
per lane-item (not week-varying); the stockout penalty is one global
number, not per item/location. A shipment can't be ordered before the
first week of the planning horizon, so a lane's lead-time-worth of
early weeks can't receive anything — an honest limitation, not a bug.

Known degeneracy from the free-holding simplification, verified while
testing: since carrying inventory costs nothing, the solver can be
mathematically indifferent between several equally-cheap allocations —
e.g. it may attribute a whole multi-week shortfall to a single week's
`unmet_demand` row instead of spreading it evenly, or ship everything
in week 1 and hold it. The TOTALS (total cost, total unmet quantity,
per-lane utilization) are always meaningful; the exact week-by-week
split among several equal-cost solutions is not guaranteed to be the
"natural" one a human would pick.
"""

import pandas as pd
from ortools.linear_solver import pywraplp


class InfeasibleError(Exception):
    pass


def solve(lanes_df: pd.DataFrame, demand_df: pd.DataFrame, starting_inventory_df: pd.DataFrame,
          stockout_penalty: float) -> dict:
    if demand_df.empty:
        raise ValueError("No demand data provided — nothing to optimize against.")
    if lanes_df.empty:
        raise ValueError("No lanes provided — nothing to ship on.")

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        raise RuntimeError("Could not create the OR-Tools GLOP solver.")
    infinity = solver.infinity()

    weeks = sorted(demand_df["week"].unique())
    first_week, last_week = weeks[0], weeks[-1]
    horizon = list(range(first_week, last_week + 1))

    demand_lookup = {
        (row["location"], row["item"], row["week"]): row["demand_qty"]
        for _, row in demand_df.iterrows()
    }
    starting_inv_lookup = {
        (row["location"], row["item"]): row["qty"] for _, row in starting_inventory_df.iterrows()
    }

    relevant_pairs = set(zip(demand_df["location"], demand_df["item"]))
    relevant_pairs |= set(zip(lanes_df["to_location"], lanes_df["item"]))
    relevant_pairs |= set(starting_inv_lookup.keys())

    lane_rows = lanes_df.to_dict("records")

    ship = {
        (r["lane_id"], r["item"], w): solver.NumVar(0, r["capacity_per_week"], f"ship_{r['lane_id']}_{r['item']}_{w}")
        for r in lane_rows
        for w in horizon
    }
    unmet = {
        (loc, item, w): solver.NumVar(0, infinity, f"unmet_{loc}_{item}_{w}")
        for (loc, item) in relevant_pairs
        for w in horizon
    }
    inventory = {
        (loc, item, w): solver.NumVar(0, infinity, f"inv_{loc}_{item}_{w}")
        for (loc, item) in relevant_pairs
        for w in horizon
    }

    # Objective: shipping cost + stockout penalty.
    solver.Minimize(
        sum(ship[(r["lane_id"], r["item"], w)] * r["cost_per_unit"] for r in lane_rows for w in horizon)
        + sum(unmet.values()) * stockout_penalty
    )

    # Inventory balance per (location, item, week).
    for (loc, item) in relevant_pairs:
        for w in horizon:
            arrivals = sum(
                (ship[(r["lane_id"], r["item"], w - r["lead_time_weeks"])]
                 for r in lane_rows
                 if r["to_location"] == loc and r["item"] == item
                 and (w - r["lead_time_weeks"]) in horizon),
                0,
            )
            prev_inv = inventory[(loc, item, w - 1)] if (w - 1) in horizon else starting_inv_lookup.get((loc, item), 0)
            demand_qty = demand_lookup.get((loc, item, w), 0)
            solver.Add(inventory[(loc, item, w)] == prev_inv + arrivals - (demand_qty - unmet[(loc, item, w)]))

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        status_names = {
            pywraplp.Solver.INFEASIBLE: "INFEASIBLE", pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
            pywraplp.Solver.ABNORMAL: "ABNORMAL", pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
        }
        raise InfeasibleError(f"Solver did not find an optimal solution (status: {status_names.get(status, status)}).")

    shipment_plan = []
    for r in lane_rows:
        for w in horizon:
            qty = ship[(r["lane_id"], r["item"], w)].solution_value()
            if qty > 1e-6:
                shipment_plan.append({
                    "lane_id": r["lane_id"], "item": r["item"], "order_week": w,
                    "arrival_week": w + r["lead_time_weeks"], "qty": qty,
                    "capacity_per_week": r["capacity_per_week"], "utilization_pct": qty / r["capacity_per_week"] * 100,
                })

    unmet_demand = []
    for (loc, item, w), var in unmet.items():
        qty = var.solution_value()
        if qty > 1e-6:
            unmet_demand.append({"location": loc, "item": item, "week": w, "unmet_qty": qty})

    total_shipping_cost = sum(
        ship[(r["lane_id"], r["item"], w)].solution_value() * r["cost_per_unit"]
        for r in lane_rows for w in horizon
    )
    total_penalty_cost = sum(u["unmet_qty"] for u in unmet_demand) * stockout_penalty

    return {
        "shipment_plan": pd.DataFrame(shipment_plan),
        "unmet_demand": pd.DataFrame(unmet_demand),
        "total_shipping_cost": total_shipping_cost,
        "total_penalty_cost": total_penalty_cost,
        "total_cost": total_shipping_cost + total_penalty_cost,
        "horizon": horizon,
    }
