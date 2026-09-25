"""Fetches real search-interest data from Google Trends.

Google Trends doesn't give raw search *counts* — it gives a relative score
from 0-100, where 100 is the peak popularity for that keyword within the
time window and region you ask for. That's still useful: it tells us
whether interest is rising, falling, or flat.
"""

from pytrends.request import TrendReq


def get_interest_over_time(keyword: str, geo: str, timeframe: str = "today 3-m"):
    """Returns a pandas DataFrame of daily interest for `keyword` in `geo`.

    geo: a country code like "US", "IN", "GB" — or "" for worldwide.
    timeframe: pytrends' own mini-syntax, "today 3-m" = last 3 months.
    """
    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload([keyword], cat=0, timeframe=timeframe, geo=geo)
    df = pytrends.interest_over_time()

    if df.empty:
        raise ValueError(
            f"No Google Trends data returned for '{keyword}' in '{geo}'. "
            "Try a more common keyword or a wider region."
        )

    return df[[keyword]]
