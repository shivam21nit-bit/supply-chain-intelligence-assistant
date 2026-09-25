# Supply Chain Intelligence Assistant

A toolkit for reasoning about a supply chain from multiple angles: how much
public interest an item has right now, what's disrupting the routes/countries
it moves through, how your own modeled network compares to real trade data,
and — given a network of lanes, costs, and demand — what the cheapest
shipment plan actually is.

Everything runs on free-tier data sources and free/open-source tools. Each
capability also works as a standalone CLI script, in addition to the unified
web UI.

## What it does

| | |
|---|---|
| **Demand Lookup** | Real Google Trends search-interest for any item + region, with spike detection and an AI-generated explanation grounded in actual news headlines (never an invented cause). |
| **Disruption Scan** | For your modeled suppliers/routes: real news search (GDELT + Google News) *and* real satellite-tracked shipping-chokepoint traffic data (IMF PortWatch), corroborating each other. |
| **My Supply Chain** | Model your own suppliers, warehouses, and routes as a graph (Neo4j), with a live visual diagram, and cross-check each route against real UN Comtrade bilateral trade statistics. |
| **Network Optimizer** | Upload or enter a full network — lanes with cost/lead-time/capacity, weekly demand — and get the actual cost-minimizing shipment plan from a real linear-programming solver (Google OR-Tools), not a heuristic. |

The graph and the optimizer are two different stores under the hood (see
[Architecture](#architecture)), kept in sync through explicit, one-click
actions rather than automatically.

## Getting started

You'll need free accounts with four external services (no cost, no credit
card for any of them). Each one has its own `.env` file, git-ignored, never
committed:

| Service | Used for | Get a key at |
|---|---|---|
| UN Comtrade | Real bilateral trade statistics | https://uncomtrade.org/docs/how-to-create-an-account/ |
| Neo4j AuraDB (Free tier) | Your supply chain graph | https://console.neo4j.io |
| Google AI Studio | AI-generated summaries (Gemini) | https://aistudio.google.com |

Each of the five folders below is a self-contained Python project with its
own virtual environment. From the repo root, for each folder:

```bash
cd <folder>
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then create that folder's `.env` (see the table in [Project layout](#project-layout)
for which keys go where) and you're ready to run it.

**Fastest path to something usable**: set up `app/` last (it imports the
other four modules via `sys.path`, so its venv needs *all* of their
dependencies too — installing `app/requirements.txt` covers this). Then:

```bash
cd app
.\venv\Scripts\streamlit.exe run app.py
```

Opens at http://localhost:8501 with all four capabilities as tabs.

## Architecture

Five independent modules, each its own folder + venv, tied together by the
`app/` Streamlit UI (which imports the others directly — no code
duplication, no network calls between modules):

- **`demand_signal/`** — Google Trends → spike detection → GDELT/Google News correlation → AI summary.
- **`disruption_feed/`** — UN Comtrade (real trade partners) → chokepoint heuristic → GDELT/Google News + IMF PortWatch (real chokepoint traffic).
- **`supply_chain_graph/`** — your own suppliers/routes, stored in Neo4j (a real graph database — genuinely relationship-shaped data, worth traversing/visualizing).
- **`network_optimizer/`** — lanes + weekly demand, stored in SQLite (tabular, time-indexed data — a relational table is the natural fit, and the solver needs a DataFrame anyway). A linear-programming solver (OR-Tools/GLOP) computes the actual optimal plan; no graph traversal is involved, so a graph database would just add overhead here.
- **`app/`** — the Streamlit UI tying all four together, plus the first LLM integration (Gemini) and explicit sync actions between the graph and the optimizer.

**Why two databases instead of one**: Neo4j's value is relationship
traversal; the optimizer's data is flat rows indexed by (lane, item, week)
that a solver consumes as a table, never traversed. Forcing one tool to do
both would fight the natural shape of one side's data. They're kept in sync
through explicit actions in the Network Optimizer tab: reusing graph
location/item names when entering optimizer data, importing an existing
graph route as a lane skeleton, and writing the optimizer's actual-used
lanes back to the graph as routes after a run.

## Project layout

| Folder | Run | `.env` needed |
|---|---|---|
| `demand_signal/` | `python main.py <item> <geo_code>` — e.g. `python main.py coffee US` | none (no API key required) |
| `disruption_feed/` | `python main.py "<item>" <destination_ISO3>` — e.g. `python main.py "crude oil" IND` | `UNCOMTRADE_API_KEY` |
| `supply_chain_graph/` | `python main.py` — interactive menu | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` |
| `network_optimizer/` | no standalone CLI — driven from `app/`'s Tab 4 or a CSV | none (local SQLite file) |
| `app/` | `streamlit run app.py` → http://localhost:8501 | `GOOGLE_API_KEY` (also reads `disruption_feed/.env`'s key for the route-analysis feature) |

`disruption_feed/hs_codes.py` only covers a small curated list of common
commodities (crude oil, wheat, coffee, etc.) — anything else gets an honest
"not found" rather than a guess.

## Known limitations

Real, current constraints worth knowing before you rely on this for anything:

- **GDELT** (the primary news source) rate-limits to ~1 request/5s and can
  throttle harder under sustained use. Both news-lookup modules fall back to
  Google News RSS automatically, and report an honest "search failed" if
  both fail — never a false "nothing found."
- **IMF PortWatch** chokepoint traffic data is real (satellite AIS) but
  noisy at a daily level — the app compares a 7-day average against a
  35-day baseline rather than trusting a single day, and still treat it as
  a rough signal, not a precise measurement.
- **UN Comtrade** trade statistics are annual, not real-time; the "cost
  proxy" it enables (customs value ÷ quantity) is not a delivered-logistics
  cost.
- **Neo4j AuraDB Free** auto-pauses after 3 days of no writes and deletes
  after 30 days with no recovery (no backups on the free tier). If you go
  quiet on this project for a while, the graph may need rebuilding.
- `supply_chain_graph` talks to Neo4j over its **HTTPS Query API**, not the
  Bolt driver — needed on a network where Bolt's port (7687) is blocked;
  works either way on an unrestricted network.
- **`network_optimizer`** models inventory carrying forward between weeks
  with **no holding cost** (not modeled — no data available for it). One
  consequence: with holding free, the solver can be mathematically
  indifferent between several equally-cheap timings, so a shortfall might
  get attributed to a single week rather than spread naturally. Trust the
  *totals* (total cost, total unmet quantity, per-lane utilization) over
  the exact week-by-week split. Capacity is also flat per lane (not
  week-varying) and the stockout penalty is one global number, not
  per-item — both are stated simplifications matching the data available
  today, not silent assumptions.
- The AI summary feature (Gemini, free tier) is explicitly instructed to
  never state a price/delay figure that isn't literally present in the
  data it's given, and to say plainly when the evidence doesn't explain
  something — but free-tier model availability shifts over time; if a
  model name breaks, the API's own error message names the replacement.
- The optimizer's solver (Google OR-Tools/GLOP) is the right choice for
  the current pure-continuous-LP model; adding minimum order quantities or
  lane-activation fixed costs later would call for OR-Tools' CP-SAT solver
  instead — a real change, not a config flag.
