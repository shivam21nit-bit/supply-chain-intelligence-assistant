# Supply Chain Intelligence Assistant

## Vision

A system that helps a user understand, for items they care about:
1. **Demand projection** — based on public interest (search/social).
2. **Supply chain disruption feed** — what's currently disrupted, and where.
3. **Price movement** for major imports/exports, by location.
4. **Route/delivery disruption** — impact on delivery time.

...tied together by a **user-modeled supply chain graph** (their own suppliers,
warehouses, routes), so the system can say: "here's what this disruption
touches in *your* chain, and here's the KPI impact."

This is a multi-agent system. It's being built one working slice at a time
instead of all at once, so there's always something real to test and react to.

## Build order

1. **Demand Signal agent** — DONE (see `demand_signal/`). Search interest by
   item + region, via Google Trends (free, no API key). Fetch → spike
   detection → news correlation (GDELT) → chart.
2. **Route-Aware Disruption Feed** — DONE (see `disruption_feed/`). Given an
   item + destination country, fetches real bilateral import data (UN
   Comtrade API), maps top source countries to a likely shipping chokepoint,
   then checks GDELT news for each chokepoint and tags it with a likely
   effect (delivery delay / price / availability) or honestly says "no
   disruption keyword matched."
3. **Supply Chain Graph** — DONE (see `supply_chain_graph/`). A guided CLI
   wizard for entering your own suppliers, warehouses, and routes, stored in
   a real Neo4j AuraDB graph database (free tier). This is also where you can
   correct/extend the chokepoint heuristics from slice 2 with your own real
   supplier data.
4. **Web UI** — DONE (see `app/`). A Streamlit app tying 1-3 together as
   three independent, on-demand actions: manage your graph (now with a
   visual diagram), look up demand trends, and scan your graph for
   disruptions. CLI scripts from 1-3 remain fully usable on their own too —
   this is a new front door, not a replacement. Includes the project's
   first real LLM call: an AI-generated "probable cause" summary (Google
   Gemini, free tier) that grounds its answer only in fetched data —
   trend numbers, real UN Comtrade trade statistics, real IMF PortWatch
   chokepoint transit-volume data, and headlines — with automatic fallback
   to heuristic headline-grouping if the LLM call fails. A "route analysis"
   section cross-checks each modeled route against real trade data
   (international routes) or news-based leads (domestic routes), since
   those two cases have genuinely different free data available.
5. **Network Optimization Engine** — DONE (see `network_optimizer/` +
   app tab 4). A different kind of capability from 1-4: not sensing, but
   an actual cost-minimizing multi-period transportation-problem solver
   (Google OR-Tools' GLOP LP solver — swapped in from an initial PuLP/CBC
   build once we discussed solver choice; see the constraint note below)
   — given a whole network's lanes (cost, lead time, capacity)
   and weekly demand, computes the cheapest real shipment plan, uploaded
   via CSV or entered manually. Its own SQLite store, deliberately
   separate from slice 3's Neo4j graph (this data is tabular/time-indexed,
   not graph-shaped) — but kept in sync with it, one button-click action
   at a time, not automatically: reuse graph location/item names when
   entering optimizer data, import an existing graph route as a lane
   skeleton, and write the optimizer's actual-used lanes back to the
   graph as routes after a run.

## Project layout

- `demand_signal/` — slice 1. Run with:
  ```
  cd demand_signal
  .\venv\Scripts\python.exe main.py <item> <geo_code>
  ```
  e.g. `python main.py coffee US`. Produces a one-line summary and
  `interest_chart_<item>_<geo>.png`.

- `disruption_feed/` — slice 2. Run with:
  ```
  cd disruption_feed
  .\venv\Scripts\python.exe main.py "<item>" <destination_ISO3>
  ```
  e.g. `python main.py "crude oil" IND`. Needs a free UN Comtrade API key in
  `disruption_feed/.env` (`UNCOMTRADE_API_KEY=...`, git-ignored, never
  hardcoded or printed) — register your own at
  https://uncomtrade.org/docs/how-to-create-an-account/. Only covers items
  listed in `hs_codes.py` (a small curated starter list); anything else gets
  an honest "not found" instead of a guess.

- `supply_chain_graph/` — slice 3. Run with:
  ```
  cd supply_chain_graph
  .\venv\Scripts\python.exe main.py
  ```
  An interactive menu to add/view/delete suppliers, warehouses, your own
  destination facility, and the routes between them. Needs a free Neo4j
  AuraDB instance's credentials in `supply_chain_graph/.env`
  (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` — all
  git-ignored, never hardcoded or printed) — register your own free
  instance at https://console.neo4j.io.

- `app/` — slice 4 (web UI). Run with:
  ```
  cd app
  .\venv\Scripts\streamlit.exe run app.py
  ```
  Opens at http://localhost:8501. Imports slice 1-3's modules directly via
  `sys.path` (no code duplication — this does mean `app/`'s venv also needs
  `comtradeapicall`, installed alongside its own `streamlit`/`pytrends`/etc.).
  Needs a free Google AI Studio API key in `app/.env` (`GOOGLE_API_KEY=...`,
  git-ignored) for the AI summary feature — register at
  https://aistudio.google.com (Anthropic's API was the original choice but
  has no free tier; swapped to Gemini's free tier instead). Also uses
  `disruption_feed/.env`'s existing `UNCOMTRADE_API_KEY` for the route
  analysis section, and the free `pycountry` package (offline, no API) to
  resolve free-text country names to ISO3 codes.

- `network_optimizer/` — slice 5, also usable standalone for testing:
  ```
  cd network_optimizer
  .\venv\Scripts\python.exe -c "import store; print(store.get_all_lanes())"
  ```
  No CLI wizard for this one (it's tabular data, best driven from the
  app's Tab 4 or a CSV) — `store.py` (SQLite, `network.db`, git-ignored)
  and `optimizer.py` (the OR-Tools/GLOP LP model) are the two files, both
  independently unit-tested against hand-calculated expected answers
  before being wired into the UI (re-verified again after the PuLP→
  OR-Tools swap — same test cases, same answers). Needs `ortools` —
  see the constraint note below.

## Notes / constraints

- Building with free/no-budget data sources for now; revisit paid APIs
  (social listening, premium news feeds) once the concept is proven.
- Each slice follows the same shape: fetch real data → tag/summarize →
  present, and never silently treat an API failure as "nothing found" —
  this became a real bug once (in both slices) and is now fixed everywhere:
  a failed request always says so explicitly.
- The free GDELT news API rate-limits to ~1 request every 5 seconds and can
  throttle harder under sustained/rapid testing. Both slices back off and
  retry, then report an honest "search failed" rather than a false "clean"
  result. Accepted as a known limitation of the free tier for now.
- `disruption_feed`'s chokepoint-per-country mapping (`chokepoints.py`) is a
  geography-based heuristic, not verified per-shipment routing — a
  placeholder for what slice 3's user-modeled graph will eventually replace
  with real data.
- `supply_chain_graph` talks to Neo4j Aura over its **HTTPS Query API**
  (`db/<database>/query/v2`), not the official Bolt driver — on a
  corporate-managed laptop with an always-on VPN (Palo Alto GlobalProtect),
  the Bolt driver's port (7687) was blocked/intercepted regardless of which
  wifi network was used, while plain HTTPS (443) was not. If you ever
  migrate this off a locked-down network, either connection method works;
  the HTTPS one is simply the more portable choice.
- Neo4j AuraDB Free auto-pauses an instance after 3 days with no write
  query, and deletes a paused instance after 30 days with no recovery (no
  automatic backups on the free tier). If you go quiet on this project for
  a while, the graph data may need to be rebuilt via the wizard.
- Both news-lookup modules (`demand_signal/news_lookup.py`,
  `disruption_feed/disruption_search.py`) try GDELT first, then fall back
  to Google News RSS if GDELT fails or comes back empty — relying on a
  single free source meant one rate-limit hit killed the whole feature.
- `app/llm_summary.py`'s model name has already changed once
  (`gemini-flash-latest` → `gemini-2.5-flash` → `gemini-3.8-flash`, the
  last two changes forced by Google deprecating the prior model for new
  users) — free-tier model availability shifts over time; if this breaks
  again, the API's own error message names the current replacement model.
- Found and fixed a real duplicate-widget bug: an editing mistake left two
  `st.expander(...)` calls back to back in `render_articles()`, and because
  neither had a `key=`, Streamlit's rerun reconciliation rendered both.
  Lesson: give explicit `key=` to any widget generated inside a function
  called more than once per page, even before hitting the bug.
- `disruption_feed/chokepoint_status.py` gets real (if noisy) chokepoint
  traffic data from IMF PortWatch's free public dataset (satellite AIS,
  updated weekly, no signup) — daily counts are small and volatile, so it
  compares a trailing 7-day average against a 35-day baseline rather than
  trusting any single day. This is the actual "is this route's chokepoint
  currently busier or quieter than normal" signal; GDELT/Google News search
  is the complementary "what's being reported about it" signal — the app
  uses both together.
- The route analysis section's "cost proxy" (customs value ÷ quantity) and
  PortWatch's transit-volume figures are the only numbers the LLM is
  allowed to cite for price/delay — it's explicitly instructed never to
  invent a specific number that isn't literally present in what it's given.
- **Solver history**: started on PuLP/CBC (hit a real breaking change —
  PuLP's now-default v4.0 rewrote its internals around a new Rust core
  and dropped the classic `LpVariable(lowBound=..., upBound=...)` API,
  so we'd pinned `pulp==2.9.0`). Swapped to **Google OR-Tools' GLOP**
  solver after discussing solver choice — GLOP is the right OR-Tools
  backend for this specific model because it's a pure continuous LP
  (no integer/MIP variables); if minimum order quantities or
  lane-activation fixed costs get added later, that's a real switch to
  OR-Tools' CP-SAT solver, not a config flag. Both solvers gave
  identical answers on the same hand-verified test cases before/after
  the swap.
- The optimizer models inventory carrying forward between weeks with
  **no holding cost** (a stated simplification — no data was available
  for it). One real consequence, verified while testing: with holding
  free, the solver can be mathematically indifferent between several
  equally-cheap timings, so it may report a whole shortfall under one
  specific week, or ship everything early and hold it, rather than the
  "natural"-looking spread a human might expect. The *totals* (total
  cost, total unmet quantity, per-lane utilization) are always
  meaningful; the exact week-by-week split isn't guaranteed to be unique.
- Capacity in `network_optimizer` is flat per lane (same number every
  week) and the stockout penalty is one global number, not per item/
  location — both stated simplifications matching the data you have
  today, documented as future enhancements in the plan rather than
  silently assumed.
