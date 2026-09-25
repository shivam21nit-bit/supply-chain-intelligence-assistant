"""Demand Signal CLI — slice 1 of the Supply Chain Intelligence Assistant.

Usage:
    python main.py <item> <geo_code>

Example:
    python main.py coffee US
"""

import re
import sys

import matplotlib.pyplot as plt

from fetch_trends import get_interest_over_time
from summarize import detect_spike, summarize_interest
from news_lookup import find_related_news


def main():
    if len(sys.argv) != 3:
        print("Usage: python main.py <item> <geo_code>")
        print("Example: python main.py coffee US")
        sys.exit(1)

    keyword = sys.argv[1]
    geo = sys.argv[2]

    print(f"Fetching Google Trends data for '{keyword}' in '{geo}'...")
    df = get_interest_over_time(keyword, geo)

    spike = detect_spike(df, keyword)
    summary = summarize_interest(keyword, geo, spike)
    print("\n" + summary)

    if spike["is_significant"]:
        print("\nLooking for news around that spike date (correlation, not confirmed cause)...")
        try:
            articles = find_related_news(keyword, spike["peak_date"])
        except RuntimeError as e:
            print(f"News search failed ({e}) — this is NOT the same as 'no disruption found'.")
        else:
            if articles:
                print("Possible related news:")
                for a in articles:
                    print(f"  - {a['title']} ({a['source']}, {a['seendate']})")
                    print(f"    {a['url']}")
            else:
                print(
                    "No related news found for this period via GDELT. This spike may just be "
                    "routine weekly/seasonal variation rather than a specific event — common for "
                    "everyday, high-volume search terms."
                )

    df.plot(title=f"Search interest for '{keyword}' in {geo} (last 3 months)")
    plt.xlabel("Date")
    plt.ylabel("Interest (0-100 scale)")
    plt.tight_layout()

    safe_keyword = re.sub(r"[^a-zA-Z0-9]+", "_", keyword).strip("_").lower()
    chart_filename = f"interest_chart_{safe_keyword}_{geo or 'world'}.png"
    try:
        plt.savefig(chart_filename)
        print(f"\nChart saved to {chart_filename}")
    except OSError as e:
        print(
            f"\nCouldn't save {chart_filename} ({e}). "
            "It's likely open in another program (e.g. an image viewer) — close it and rerun."
        )


if __name__ == "__main__":
    main()
