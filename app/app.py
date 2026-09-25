"""Supply Chain Intelligence Assistant — Web UI (slice 4).

Ties together slices 1-3 as three independent, on-demand actions:
manage your supply chain graph, look up demand trends, and scan your
graph for disruptions. Reuses the exact same functions the CLI scripts
use — nothing in slices 1-3 was rewritten, this is a new front door.

Run with: streamlit run app.py
"""

import os
import re
import sys
import time

import altair as alt
import pandas as pd
import streamlit as st

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
for sibling in ["supply_chain_graph", "disruption_feed", "demand_signal", "network_optimizer"]:
    sys.path.insert(0, os.path.join(PROJECT_DIR, sibling))

from graph_store import NODE_TYPES, add_edge, add_node, delete_edge, delete_node, get_all_edges, get_all_nodes  # noqa: E402
from disruption_search import search_recent_news  # noqa: E402
from fetch_trends import get_interest_over_time  # noqa: E402
from summarize import detect_spike, summarize_interest  # noqa: E402
from news_lookup import find_related_news  # noqa: E402
from chokepoints import get_likely_chokepoints, get_routing_note, get_lead_time_note  # noqa: E402
from chokepoint_status import get_chokepoint_status  # noqa: E402
from hs_codes import get_hs_code  # noqa: E402
from trade_data import get_top_import_sources  # noqa: E402

from llm_summary import summarize_cause  # noqa: E402
from country_lookup import resolve_iso3  # noqa: E402

import store as netopt_store  # noqa: E402
from optimizer import solve as solve_network, InfeasibleError  # noqa: E402

MODES = ["sea", "air", "road", "rail"]


# Cache network-touching lookups for 15 minutes so repeated clicks (or
# accidental double-clicks) during a session don't re-hit these free,
# rate-limited APIs for the exact same query. Failures aren't cached —
# only successful results — so a transient error still retries live.
@st.cache_data(ttl=900, show_spinner=False)
def cached_interest_over_time(item: str, geo: str):
    return get_interest_over_time(item, geo)


@st.cache_data(ttl=900, show_spinner=False)
def cached_related_news(item: str, peak_date, window_days: int = 3):
    return find_related_news(item, peak_date, window_days)


@st.cache_data(ttl=900, show_spinner=False)
def cached_disruption_search(query: str):
    return search_recent_news(query)


@st.cache_data(ttl=900, show_spinner=False)
def cached_llm_summary(subject: str, context_lines: list[str], articles: list[dict]) -> str:
    return summarize_cause(subject, context_lines, articles)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_chokepoint_status(chokepoint: str):
    return get_chokepoint_status(chokepoint)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_top_import_sources(hs_code: str, destination_iso3: str):
    return get_top_import_sources(hs_code, destination_iso3)


def chokepoint_status_line(chokepoint: str) -> str:
    """One-line, honest summary of a chokepoint's PortWatch status, for
    use both on screen and as grounded LLM context."""
    try:
        status = cached_chokepoint_status(chokepoint)
    except ValueError as e:
        return f"{chokepoint}: {e}"
    except RuntimeError as e:
        return f"{chokepoint}: PortWatch check failed ({e})."
    pct = status["pct_change"]
    direction = "below" if pct is not None and pct < 0 else "above"
    pct_str = f"{abs(pct):.0f}% {direction} its {status['baseline_days']}-day average" if pct is not None else "no baseline available"
    return (
        f"{chokepoint}: recent vessel transit calls are {pct_str} "
        f"(as of {status['as_of_date']}, PortWatch satellite AIS data — a noisy proxy, not a precise count)."
    )


_STOPWORDS = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with", "new", "at", "is", "are"}


def _title_signature(title: str) -> frozenset:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return frozenset(w for w in words if len(w) > 2 and w not in _STOPWORDS)


def group_similar_articles(articles: list[dict]) -> list[dict]:
    """Groups near-duplicate headlines (the same wire story picked up by
    multiple outlets) so the UI can show one representative line instead
    of a wall of repeated links. Word-overlap based, no LLM involved —
    same honest-heuristic spirit as the rest of this project."""
    groups: list[dict] = []
    for article in articles:
        sig = _title_signature(article["title"])
        match = next(
            (g for g in groups if sig and g["signature"]
             and len(sig & g["signature"]) / len(sig | g["signature"]) >= 0.6),
            None,
        )
        if match:
            match["members"].append(article)
        else:
            groups.append({"representative": article, "members": [article], "signature": sig})
    groups.sort(key=lambda g: len(g["members"]), reverse=True)
    return groups


def _render_heuristic_groups(articles: list[dict], tag_key: str | None):
    groups = group_similar_articles(articles)
    st.write("**Probable cause(s), based on real news coverage:**")
    for g in groups[:3]:
        rep = g["representative"]
        extra = f" (+{len(g['members']) - 1} more source{'s' if len(g['members']) > 2 else ''} reporting this)" if len(g["members"]) > 1 else ""
        tag = f"[{rep[tag_key] or 'no disruption keyword matched — review manually'}] " if tag_key else ""
        st.write(f"- {tag}{rep['title']} — {rep['source']} ({rep['via']}){extra}")


def render_articles(articles: list[dict], key: str, subject: str | None = None, context_lines: list[str] | None = None, tag_key: str | None = None):
    """Tries an AI-generated summary grounded in the headlines + known
    context; falls back to the heuristic grouped-headline display if the
    LLM call fails, degrading gracefully rather than breaking the page.
    Every individual article is always available in the expander below,
    regardless of which summary path was used.

    `key` must be unique per call site (e.g. per query in a scan loop) —
    without one, Streamlit's rerun reconciliation can render the expander
    twice, since it falls back to positional matching for unkeyed widgets."""
    if subject is not None:
        try:
            with st.spinner("Generating AI summary..."):
                summary = cached_llm_summary(subject, context_lines or [], articles)
        except RuntimeError as e:
            st.caption(f"AI summary unavailable ({e}) — showing headline grouping instead.")
            _render_heuristic_groups(articles, tag_key)
        else:
            st.write(f"**Probable cause (AI summary):** {summary}")
    else:
        _render_heuristic_groups(articles, tag_key)

    with st.expander(f"Show all {len(articles)} article(s) found", key=f"expander_{key}"):
        for a in articles:
            st.write(f"- ({a['via']}) [{a['title']}]({a['url']}) ({a['source']}, {a['seendate']})")

_NODE_COLORS = {"Supplier": "#f4a259", "Warehouse": "#8ecae6", "Destination": "#90be6d"}


def build_graph_dot(nodes: list[dict], edges: list[dict]) -> str:
    """Builds a Graphviz DOT string from the graph — rendered client-side
    by st.graphviz_chart, no system Graphviz install or extra pip package
    needed for a raw DOT string."""
    lines = ["digraph G {", '  rankdir="LR";', '  node [shape=box, style=filled, fontname="Helvetica"];']
    for n in nodes:
        label = f"{n['name']}\\n({n['type']}, {n['country']})"
        color = _NODE_COLORS.get(n["type"], "#cccccc")
        lines.append(f'  "{n["name"]}" [label="{label}", fillcolor="{color}"];')
    for e in edges:
        label = f"{e['item']} ({e['mode']})"
        lines.append(f'  "{e["from_name"]}" -> "{e["to_name"]}" [label="{label}", fontname="Helvetica"];')
    lines.append("}")
    return "\n".join(lines)


_NEW_NAME_OPTION = "+ New..."


def name_or_new_input(label: str, existing_options: list[str], key: str) -> str:
    """A selectbox of existing names (e.g. from the Neo4j graph) plus a
    '+ New...' option that reveals a text input — reuses names already
    modeled elsewhere in the app instead of risking a retyped variant
    ('India' vs 'india'), while still allowing a genuinely new name.
    Must be used OUTSIDE an st.form: forms only rerun on submit, so a
    conditional widget inside one wouldn't appear until then."""
    choice = st.selectbox(label, existing_options + [_NEW_NAME_OPTION], key=f"{key}_select")
    if choice == _NEW_NAME_OPTION:
        return st.text_input(f"New {label.lower()}", key=f"{key}_new")
    return choice


st.set_page_config(page_title="Supply Chain Intelligence Assistant", layout="wide")
st.title("Supply Chain Intelligence Assistant")

tab_graph, tab_demand, tab_disruption, tab_optimizer = st.tabs(
    ["My Supply Chain", "Demand Lookup", "Disruption Scan", "Network Optimizer"]
)

try:
    nodes = get_all_nodes()
    edges = get_all_edges()
    graph_load_error = None
except RuntimeError as e:
    nodes, edges = [], []
    graph_load_error = str(e)

# --- Tab 1: My Supply Chain ---
with tab_graph:
    if graph_load_error:
        st.error(f"Could not load your graph from Neo4j ({graph_load_error}). Try refreshing.")

    st.subheader(f"Current graph: {len(nodes)} nodes, {len(edges)} routes")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("Nodes")
        if nodes:
            st.dataframe(pd.DataFrame(nodes)[["name", "type", "country", "items"]], use_container_width=True)
        else:
            st.info("No nodes yet — add one below.")
    with col2:
        st.caption("Routes")
        if edges:
            st.dataframe(pd.DataFrame(edges), use_container_width=True)
        else:
            st.info("No routes yet — add nodes first, then a route.")

    if nodes:
        st.caption("Diagram")
        st.graphviz_chart(build_graph_dot(nodes, edges))

    st.divider()
    st.subheader("Add a node")
    with st.form("add_node_form", clear_on_submit=True):
        node_type = st.selectbox("Type", sorted(NODE_TYPES))
        name = st.text_input("Name (must be unique)")
        country = st.text_input("Country")
        items_raw = st.text_input("Item(s), comma-separated")
        if st.form_submit_button("Add node"):
            items = [i.strip() for i in items_raw.split(",") if i.strip()]
            if not name:
                st.error("Name is required.")
            else:
                try:
                    add_node(node_type, name, country, items)
                except RuntimeError as e:
                    st.error(f"Failed to add node (name may already exist): {e}")
                else:
                    st.success(f"Added {node_type} '{name}'.")
                    st.rerun()

    st.subheader("Add a route")
    if len(nodes) < 2:
        st.info("Add at least 2 nodes before adding a route.")
    else:
        names = [n["name"] for n in nodes]
        with st.form("add_edge_form", clear_on_submit=True):
            from_name = st.selectbox("From", names)
            to_name = st.selectbox("To", names)
            item = st.text_input("Item carried")
            mode = st.selectbox("Mode", MODES)
            notes = st.text_input("Notes (optional, e.g. a chokepoint)")
            if st.form_submit_button("Add route"):
                try:
                    add_edge(from_name, to_name, item, mode, notes)
                except ValueError as e:
                    st.error(f"Failed to add route: {e}")
                else:
                    st.success(f"Added route: {from_name} -> {to_name} ({item}, {mode}).")
                    st.rerun()

    st.divider()
    st.subheader("Delete")
    del_col1, del_col2 = st.columns(2)
    with del_col1:
        if nodes:
            name_to_delete = st.selectbox("Delete a node", [n["name"] for n in nodes], key="del_node")
            if st.button("Delete node"):
                route_count = delete_node(name_to_delete)
                st.success(f"Deleted '{name_to_delete}' and {route_count} attached route(s).")
                st.rerun()
        else:
            st.caption("No nodes to delete.")
    with del_col2:
        if edges:
            edge_labels = [f"{e['from_name']} -> {e['to_name']} ({e['item']}, {e['mode']})" for e in edges]
            edge_choice = st.selectbox("Delete a route", edge_labels, key="del_edge")
            if st.button("Delete route"):
                idx = edge_labels.index(edge_choice)
                e = edges[idx]
                deleted = delete_edge(e["from_name"], e["to_name"])
                st.success("Deleted." if deleted else "Route not found (already deleted?).")
                st.rerun()
        else:
            st.caption("No routes to delete.")

    st.divider()
    st.subheader("Route analysis (real trade data + current chokepoint status)")
    st.caption(
        "International routes are checked against real UN Comtrade trade statistics "
        "and IMF PortWatch chokepoint transit data. Domestic routes (same country) "
        "aren't covered by international trade stats, so these get a news-based leads "
        "search instead — weaker evidence, clearly labeled as such."
    )

    if edges and st.button("Analyze my routes"):
        node_country = {n["name"]: n["country"] for n in nodes}
        for i, e in enumerate(edges):
            if i > 0:
                time.sleep(3)
            from_country = node_country.get(e["from_name"], "")
            to_country = node_country.get(e["to_name"], "")
            st.markdown(f"**{e['from_name']} -> {e['to_name']}** ({e['item']}, {e['mode']})")

            from_iso3 = resolve_iso3(from_country)
            to_iso3 = resolve_iso3(to_country)
            is_domestic = bool(from_iso3 and to_iso3 and from_iso3 == to_iso3)

            if is_domestic:
                st.caption(
                    "Domestic route (same country) — UN Comtrade doesn't apply here "
                    "(it's bilateral international trade data only). Searching for "
                    "news-based leads instead..."
                )
                query = f'"{e["item"]}" suppliers OR production {to_country}'
                try:
                    articles = cached_disruption_search(query)
                except RuntimeError as ex:
                    st.warning(f"Search failed ({ex}).")
                    continue
                if not articles:
                    st.info(
                        "No relevant news leads found. Check that country's trade/"
                        "industry ministry site directly for real alternates — this "
                        "isn't something free news search can reliably find."
                    )
                    continue
                render_articles(articles, key=f"domestic_{i}")
                st.caption(
                    "These are news-based leads, not a verified supplier directory — "
                    "weaker evidence than the international side's real trade statistics."
                )
                continue

            hs_code = get_hs_code(e["item"])
            if not hs_code:
                st.info(
                    f"No curated HS code for '{e['item']}' — can't check real trade data "
                    "for this item (see disruption_feed/hs_codes.py for the covered list)."
                )
                continue
            if not to_iso3:
                st.info(f"Couldn't resolve '{to_country}' to a country code — skipping real trade check.")
                continue

            try:
                result = cached_top_import_sources(hs_code, to_iso3)
            except (ValueError, RuntimeError) as ex:
                st.warning(f"UN Comtrade check failed ({ex}).")
                continue

            source_names = [s["country"] for s in result["sources"]]
            matched = any(
                from_country.strip().lower() in s.lower() or s.lower() in from_country.strip().lower()
                for s in source_names
            )
            if matched:
                st.success(f"Matches real UN Comtrade data ({result['year']}): '{from_country}' is a real top source.")
            else:
                st.warning(
                    f"Real UN Comtrade data ({result['year']}) does NOT show '{from_country}' among the "
                    f"top {len(source_names)} sources for '{e['item']}' into {to_country}. Your modeled "
                    "route may be a minor/indirect supplier, or this may be a niche relationship the data "
                    f"doesn't surface. Real top sources: {', '.join(source_names)}."
                )

            context_lines = [f"Real UN Comtrade top sources for '{e['item']}' into {to_country} ({result['year']}):"]
            for s in result["sources"]:
                cost_str = f", ~${s['unit_value_per_kg']:.2f}/kg customs value" if s["unit_value_per_kg"] else ""
                context_lines.append(f"- {s['country']}: {s['share_pct']:.1f}% share{cost_str}")

            checked_countries = {from_country} | set(source_names[:3])
            for country_to_check in checked_countries:
                for cp in get_likely_chokepoints(country_to_check):
                    context_lines.append(chokepoint_status_line(cp))
                    note = get_lead_time_note(cp)
                    if note:
                        context_lines.append(f"{cp} structural note: {note}")

            with st.expander(f"Real trade data + chokepoint status details", key=f"route_details_{i}"):
                for line in context_lines:
                    st.write(f"- {line}")

            subject = f"Route {e['from_name']} ({from_country}) -> {e['to_name']} ({to_country}) for '{e['item']}'"
            try:
                with st.spinner("Generating AI route analysis..."):
                    analysis = cached_llm_summary(subject, context_lines, [])
            except RuntimeError as ex:
                st.caption(f"AI analysis unavailable ({ex}).")
            else:
                st.write(f"**AI route analysis:** {analysis}")

# --- Tab 2: Demand Lookup ---
with tab_demand:
    st.subheader("Check current demand interest for any item")
    d_col1, d_col2 = st.columns(2)
    with d_col1:
        item_query = st.text_input("Item", placeholder="e.g. coffee")
    with d_col2:
        geo_query = st.text_input("Geo code (2-letter, or blank for worldwide)", placeholder="e.g. US")

    if st.button("Check demand"):
        try:
            df = cached_interest_over_time(item_query, geo_query)
        except ValueError as e:
            st.error(str(e))
        else:
            spike = detect_spike(df, item_query)
            summary = summarize_interest(item_query, geo_query or "worldwide", spike)
            st.write(summary)

            chart_df = df.reset_index()
            date_col, value_col = chart_df.columns[0], chart_df.columns[1]
            chart = (
                alt.Chart(chart_df)
                .mark_line()
                .encode(
                    x=alt.X(f"{date_col}:T", title="Date", axis=alt.Axis(format="%b %d", labelAngle=-45)),
                    y=alt.Y(f"{value_col}:Q", title="Interest (0-100)"),
                    tooltip=[
                        alt.Tooltip(f"{date_col}:T", title="Date", format="%b %d, %Y"),
                        alt.Tooltip(f"{value_col}:Q", title="Interest"),
                    ],
                )
                .properties(height=350)
            )
            st.altair_chart(chart, use_container_width=True)

            if spike["is_significant"]:
                st.caption("Checking for news around that spike (correlation, not confirmed cause)...")
                try:
                    articles = cached_related_news(item_query, spike["peak_date"])
                except RuntimeError as e:
                    st.warning(f"News search failed ({e}) — this is NOT the same as 'no news'.")
                else:
                    if articles:
                        subject = f"'{item_query}' search demand in {geo_query or 'worldwide'}"
                        render_articles(articles, key=f"demand_{item_query}_{geo_query}", subject=subject, context_lines=[summary])
                    else:
                        st.info(
                            "No related news found. This spike may just be routine "
                            "weekly/seasonal variation rather than a specific event."
                        )

# --- Tab 3: Disruption Scan ---
with tab_disruption:
    st.subheader("Scan your supply chain for current disruption signals")
    st.caption(
        "Checks GDELT + Google News for each Supplier/Warehouse node's country, each "
        "route's notes field, AND each likely chokepoint's real IMF PortWatch transit "
        "status. Heuristic keyword tagging + a noisy real-data proxy — not a verified assessment."
    )

    if st.button("Scan my supply chain"):
        if graph_load_error:
            st.error(f"Can't scan — your graph failed to load ({graph_load_error}).")
            st.stop()

        queries: dict[str, list[str]] = {}
        chokepoint_queries: set[str] = set()
        node_chokepoints: dict[str, list[str]] = {}

        for n in nodes:
            if n["type"] in ("Supplier", "Warehouse") and n["country"]:
                queries.setdefault(n["country"], []).append(n["name"])
                cps = get_likely_chokepoints(n["country"])
                node_chokepoints[n["country"]] = cps
                for cp in cps:
                    queries.setdefault(cp, []).append(n["name"])
                    chokepoint_queries.add(cp)
        for e in edges:
            if e["notes"]:
                queries.setdefault(e["notes"], []).append(f"{e['from_name']} -> {e['to_name']}")

        if not queries:
            st.info(
                "Nothing to check yet — add Supplier/Warehouse nodes (with a country) "
                "or routes with notes in the 'My Supply Chain' tab first."
            )

        for i, (query, refs) in enumerate(queries.items()):
            if i > 0:
                time.sleep(8)  # GDELT allows only ~1 request every 5 seconds
            with st.spinner(f"Checking '{query}'..."):
                st.markdown(f"**{query}** (relevant to: {', '.join(refs)})")

                context_lines = []
                if query in chokepoint_queries:
                    context_lines.append(chokepoint_status_line(query))
                    note = get_lead_time_note(query)
                    if note:
                        context_lines.append(f"Structural note: {note}")
                    for country, cps in node_chokepoints.items():
                        if query in cps and len(cps) > 1:
                            for alt in cps:
                                if alt != query:
                                    context_lines.append(f"Alternate per our routing data — {chokepoint_status_line(alt)}")
                    st.caption(chokepoint_status_line(query))

                try:
                    articles = cached_disruption_search(query)
                except RuntimeError as e:
                    st.error(f"Search failed ({e}) — this is NOT the same as 'no disruption found'.")
                    continue
                if not articles:
                    st.info("No recent news found (checked GDELT + Google News).")
                    continue
                subject = f"'{query}' (relevant supply chain nodes/routes: {', '.join(refs)})"
                render_articles(articles, key=f"disruption_{i}_{query}", subject=subject, context_lines=context_lines, tag_key="effect")

# --- Tab 4: Network Optimizer ---
with tab_optimizer:
    st.subheader("Optimize shipment plan across your full network")
    st.caption(
        "A real cost-minimizing multi-period transportation model (not a heuristic or an "
        "LLM summary) — given lanes (cost, lead time, capacity) and weekly demand, computes "
        "the cheapest shipment plan, allowing unmet demand at a penalty cost instead of "
        "treating an under-supplied network as infeasible. Separate from the graph in the "
        "'My Supply Chain' tab — this is its own data store, sized for larger networks."
    )

    st.markdown("### 1. Load your network")
    upload_col1, upload_col2 = st.columns(2)

    with upload_col1:
        st.markdown(
            "**Lanes** — `lane_id, from_location, to_location, item, cost_per_unit, "
            "lead_time_weeks, capacity_per_week`"
        )
        lanes_template = pd.DataFrame(columns=[
            "lane_id", "from_location", "to_location", "item",
            "cost_per_unit", "lead_time_weeks", "capacity_per_week",
        ])
        st.download_button(
            "Download lanes template", lanes_template.to_csv(index=False),
            file_name="lanes_template.csv", key="dl_lanes_template",
        )
        lanes_upload = st.file_uploader("Upload lanes CSV", type="csv", key="lanes_upload")
        if lanes_upload is not None:
            try:
                n = netopt_store.load_lanes_df(pd.read_csv(lanes_upload))
            except ValueError as e:
                st.error(str(e))
            else:
                st.success(f"Loaded {n} lane row(s).")
                st.rerun()

    with upload_col2:
        st.markdown("**Demand** — `location, item, week, demand_qty`")
        demand_template = pd.DataFrame(columns=["location", "item", "week", "demand_qty"])
        st.download_button(
            "Download demand template", demand_template.to_csv(index=False),
            file_name="demand_template.csv", key="dl_demand_template",
        )
        demand_upload = st.file_uploader("Upload demand CSV", type="csv", key="demand_upload")
        if demand_upload is not None:
            try:
                n = netopt_store.load_demand_df(pd.read_csv(demand_upload))
            except ValueError as e:
                st.error(str(e))
            else:
                st.success(f"Loaded {n} demand row(s).")
                st.rerun()

    current_lanes = netopt_store.get_all_lanes()
    current_demand = netopt_store.get_all_demand()
    current_inventory = netopt_store.get_starting_inventory()

    st.markdown(f"**Currently loaded:** {len(current_lanes)} lane row(s), {len(current_demand)} demand row(s).")
    if not current_lanes.empty:
        st.caption("Lanes")
        st.dataframe(current_lanes, use_container_width=True)
    if not current_demand.empty:
        st.caption("Demand")
        st.dataframe(current_demand, use_container_width=True)

    graph_location_names = [n["name"] for n in nodes]
    graph_item_names = sorted({item for n in nodes for item in n["items"]})

    with st.expander("Or add rows manually (for smaller networks)"):
        st.caption(
            "Location/item pickers below reuse names already in your 'My Supply Chain' "
            "graph where possible — pick '+ New...' to type a name that doesn't exist there yet."
        )
        st.caption("Add a single lane")
        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            lane_id = st.text_input("Lane ID", key="lane_id_input")
            from_loc = name_or_new_input("From location", graph_location_names, "lane_from")
        with lc2:
            to_loc = name_or_new_input("To location", graph_location_names, "lane_to")
            lane_item = name_or_new_input("Item", graph_item_names, "lane_item")
        with lc3:
            cost = st.number_input("Cost per unit", min_value=0.0, step=0.1, key="lane_cost")
            lead_time = st.number_input("Lead time (weeks)", min_value=0, step=1, key="lane_leadtime")
            capacity = st.number_input("Capacity per week", min_value=0.0, step=1.0, key="lane_capacity")
        if st.button("Add lane"):
            if not (lane_id and from_loc and to_loc and lane_item):
                st.error("Lane ID, from/to location, and item are all required.")
            else:
                netopt_store.add_lane(lane_id, from_loc, to_loc, lane_item, cost, int(lead_time), capacity)
                st.success(f"Added lane {lane_id}.")
                st.rerun()

        st.divider()
        st.caption("Add a single demand row")
        dc1, dc2, dc3 = st.columns(3)
        with dc1:
            d_loc = name_or_new_input("Location", graph_location_names, "demand_loc")
        with dc2:
            d_item = name_or_new_input("Item", graph_item_names, "demand_item")
        with dc3:
            d_week = st.number_input("Week", min_value=1, step=1, key="demand_week")
        d_qty = st.number_input("Demand quantity", min_value=0.0, step=1.0, key="demand_qty")
        if st.button("Add demand row"):
            if not (d_loc and d_item):
                st.error("Location and item are required.")
            else:
                netopt_store.add_demand_row(d_loc, d_item, int(d_week), d_qty)
                st.success("Added demand row.")
                st.rerun()

    with st.expander("Import a route from my graph"):
        existing_lane_keys = set(zip(current_lanes.get("from_location", []), current_lanes.get("to_location", []), current_lanes.get("item", [])))
        importable = [e for e in edges if (e["from_name"], e["to_name"], e["item"]) not in existing_lane_keys]
        if not importable:
            st.caption("No new routes to import — every graph route is already a lane, or your graph has none yet.")
        else:
            route_labels = [f"{e['from_name']} -> {e['to_name']} ({e['item']}, {e['mode']})" for e in importable]
            route_choice = st.selectbox("Graph route", route_labels, key="import_route_choice")
            chosen_edge = importable[route_labels.index(route_choice)]
            ic1, ic2, ic3 = st.columns(3)
            with ic1:
                import_lane_id = st.text_input("Lane ID for this import", value=f"{chosen_edge['from_name']}_{chosen_edge['to_name']}", key="import_lane_id")
            with ic2:
                import_cost = st.number_input("Cost per unit", min_value=0.0, step=0.1, key="import_cost")
                import_leadtime = st.number_input("Lead time (weeks)", min_value=0, step=1, key="import_leadtime")
            with ic3:
                import_capacity = st.number_input("Capacity per week", min_value=0.0, step=1.0, key="import_capacity")
            if st.button("Import this route as a lane"):
                netopt_store.add_lane(
                    import_lane_id, chosen_edge["from_name"], chosen_edge["to_name"], chosen_edge["item"],
                    import_cost, int(import_leadtime), import_capacity,
                )
                st.success(f"Imported '{route_choice}' as lane {import_lane_id}.")
                st.rerun()

    st.divider()
    st.markdown("### 2. Run the optimization")

    default_penalty = round(current_lanes["cost_per_unit"].mean() * 10, 2) if not current_lanes.empty else 100.0
    stockout_penalty = st.number_input(
        "Stockout penalty cost per unmet unit",
        min_value=0.0, value=default_penalty, step=1.0,
        help="Cost charged per unit of demand that can't be met. Default shown is 10x your "
        "average lane cost — override if you have a real figure.",
    )

    if st.button("Run optimization"):
        try:
            result = solve_network(current_lanes, current_demand, current_inventory, stockout_penalty)
        except ValueError as e:
            st.error(str(e))
        except InfeasibleError as e:
            st.error(f"Solver could not find a solution: {e}")
        else:
            # Stashed in session_state (not just a local var) so the "Sync to
            # graph" button below still has it after the rerun that button click causes.
            st.session_state["netopt_last_result"] = result
            st.session_state["netopt_last_lanes"] = current_lanes

    if "netopt_last_result" in st.session_state:
        result = st.session_state["netopt_last_result"]
        lanes_used_for_run = st.session_state["netopt_last_lanes"]

        st.success(
            f"Total cost: {result['total_cost']:,.2f} "
            f"(shipping: {result['total_shipping_cost']:,.2f}, "
            f"stockout penalty: {result['total_penalty_cost']:,.2f})"
        )
        st.caption(
            "With no holding cost modeled, the solver can be mathematically indifferent "
            "between several equally-cheap timings — trust the totals and per-lane "
            "utilization over the exact week-by-week split of shipments/unmet demand."
        )

        st.markdown("**Shipment plan**")
        if not result["shipment_plan"].empty:
            st.dataframe(result["shipment_plan"], use_container_width=True)
        else:
            st.info("No shipments in the optimal plan.")

        st.markdown("**Unmet demand**")
        if not result["unmet_demand"].empty:
            st.warning("Some demand could not be met at the given capacity/cost tradeoff — see below.")
            st.dataframe(result["unmet_demand"], use_container_width=True)
        else:
            st.info("All demand was met.")

        st.divider()
        st.caption(
            "Writes each lane actually used in this plan back to your 'My Supply Chain' "
            "graph as a route (tagged 'optimized'), skipping any lane whose location isn't "
            "already a node there instead of guessing or creating one."
        )
        if st.button("Sync optimal plan back to graph"):
            if result["shipment_plan"].empty:
                st.info("Nothing to sync — the optimal plan has no shipments.")
            else:
                lane_lookup = {(r["lane_id"], r["item"]): r for _, r in lanes_used_for_run.iterrows()}
                existing_edge_keys = {(e["from_name"], e["to_name"], e["item"]) for e in edges}
                used = result["shipment_plan"][["lane_id", "item"]].drop_duplicates()

                synced, skipped, already_there = [], [], []
                for _, row in used.iterrows():
                    lane_row = lane_lookup.get((row["lane_id"], row["item"]))
                    if lane_row is None:
                        continue
                    from_loc, to_loc, item = lane_row["from_location"], lane_row["to_location"], row["item"]
                    if (from_loc, to_loc, item) in existing_edge_keys:
                        already_there.append(row["lane_id"])
                        continue
                    util = result["shipment_plan"].loc[
                        (result["shipment_plan"]["lane_id"] == row["lane_id"])
                        & (result["shipment_plan"]["item"] == item),
                        "utilization_pct",
                    ].mean()
                    try:
                        add_edge(from_loc, to_loc, item, "optimized",
                                  f"From network optimizer (lane {row['lane_id']}, avg utilization {util:.0f}%)")
                        synced.append(row["lane_id"])
                    except ValueError:
                        skipped.append(f"'{row['lane_id']}': '{from_loc}' or '{to_loc}' isn't a node in your graph yet — add it in the 'My Supply Chain' tab first.")

                if synced:
                    st.success(f"Synced {len(synced)} lane(s) to your graph: {', '.join(synced)}.")
                if already_there:
                    st.caption(f"Already present as routes: {', '.join(already_there)}.")
                for msg in skipped:
                    st.warning(f"Skipped {msg}")
                if synced:
                    st.rerun()
