"""Route-Aware Disruption Feed CLI — slice 2 of the Supply Chain
Intelligence Assistant.

Usage:
    python main.py "<item>" <destination_ISO3>

Example:
    python main.py "crude oil" IND
"""

import sys
import time

from hs_codes import get_hs_code
from trade_data import get_top_import_sources
from chokepoints import get_likely_chokepoints, get_routing_note
from disruption_search import search_recent_news


def main():
    if len(sys.argv) != 3:
        print('Usage: python main.py "<item>" <destination_ISO3>')
        print('Example: python main.py "crude oil" IND')
        sys.exit(1)

    item = sys.argv[1]
    destination = sys.argv[2]

    hs_code = get_hs_code(item)
    if not hs_code:
        print(
            f"No curated HS code found for '{item}'. This module only covers a small "
            "starter list of common commodities (see hs_codes.py) — try one of those, "
            "or ask me to add this item to the list."
        )
        sys.exit(1)

    print(f"Looking up real import data for '{item}' (HS {hs_code}) into {destination}...")
    try:
        result = get_top_import_sources(hs_code, destination)
    except (ValueError, RuntimeError) as e:
        print(f"Could not fetch trade data: {e}")
        sys.exit(1)

    print(f"\nTop sources of '{item}' imports into {destination} in {result['year']} "
          f"(real UN Comtrade data):")
    for s in result["sources"]:
        share = f"{s['share_pct']:.1f}%" if s["share_pct"] is not None else "n/a"
        print(f"  - {s['country']}: ${s['value_usd']:,.0f} ({share} of total imports)")

    seen_chokepoints = {}
    for s in result["sources"]:
        chokepoints = get_likely_chokepoints(s["country"])
        if not chokepoints:
            print(f"\nNo chokepoint heuristic available for {s['country']} — skipping route check.")
            continue
        note = get_routing_note(s["country"])
        if note:
            print(f"\nNote on {s['country']} routing: {note}")
        for cp in chokepoints:
            seen_chokepoints.setdefault(cp, []).append(s["country"])

    print("\n--- Route disruption check (heuristic chokepoints, last 21 days) ---")
    for i, (chokepoint, countries) in enumerate(seen_chokepoints.items()):
        if i > 0:
            time.sleep(8)  # GDELT allows only 1 request every 5 seconds
        print(f"\n{chokepoint} (relevant to: {', '.join(countries)}):")
        try:
            articles = search_recent_news(chokepoint)
        except RuntimeError as e:
            print(f"  Search failed ({e}) — this is NOT the same as 'no disruption found'.")
            continue
        if not articles:
            print("  No recent news found for this chokepoint via GDELT.")
            continue
        for a in articles:
            tag = a["effect"] or "no disruption keyword matched — review manually"
            print(f"  - [{tag}] {a['title']} ({a['source']}, {a['seendate']})")
            print(f"    {a['url']}")


if __name__ == "__main__":
    main()
