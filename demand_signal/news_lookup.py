"""Looks up real news articles near a given date, to help explain a
Google Trends spike.

Tries two independent free sources, since relying on just one (GDELT)
means a single rate-limit hit kills the whole feature:

1. GDELT Doc API (https://www.gdeltproject.org/) — no signup, no key,
   supports precise historical date-range search, but rate-limits to
   ~1 request/5s and can stay stubborn under sustained testing.
2. Google News RSS — no signup, no key, no documented rate limit, but
   only surfaces currently-indexed/recent-ish articles rather than a
   true historical archive query, so it's a real fallback, not a
   like-for-like replacement.

Important honesty check either way: this only shows articles that
mention the keyword near the relevant time. That's a *correlation*,
not a confirmed cause.
"""

import time
import xml.etree.ElementTree as ET
from datetime import timedelta

import requests

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def _gdelt_get_with_retry(params: dict, attempts: int = 3, backoff_seconds: int = 15):
    last_error = None
    for _ in range(attempts):
        try:
            response = requests.get(GDELT_DOC_API, params=params, timeout=15)
        except requests.RequestException as e:
            last_error = f"GDELT request failed ({e.__class__.__name__}): {e}"
            time.sleep(backoff_seconds)
            continue

        if response.status_code == 429:
            last_error = "GDELT rate limit hit (max 1 request every 5 seconds)."
            time.sleep(backoff_seconds)
            continue

        response.raise_for_status()
        return response

    raise RuntimeError(f"{last_error} Gave up after {attempts} attempts.")


def _search_gdelt(keyword: str, start: str, end: str, max_results: int) -> list[dict]:
    params = {
        "query": keyword,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_results,
        "startdatetime": start,
        "enddatetime": end,
        "sort": "HybridRel",
    }
    response = _gdelt_get_with_retry(params)

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"GDELT returned a non-JSON response: {response.text[:200]!r}")

    articles = data.get("articles", [])
    return [
        {
            "title": a.get("title"),
            "url": a.get("url"),
            "source": a.get("domain"),
            "seendate": a.get("seendate"),
            "via": "GDELT",
        }
        for a in articles
        if a.get("title")
    ]


def _search_google_news_rss(keyword: str, max_results: int) -> list[dict]:
    try:
        response = requests.get(
            GOOGLE_NEWS_RSS,
            params={"q": keyword, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Google News RSS request failed ({e.__class__.__name__}): {e}")

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        raise RuntimeError(f"Google News RSS returned unparseable XML: {e}")

    results = []
    for item in root.findall("./channel/item")[:max_results]:
        title = item.findtext("title")
        if not title:
            continue
        source_el = item.find("source")
        results.append(
            {
                "title": title,
                "url": item.findtext("link"),
                "source": source_el.text if source_el is not None else None,
                "seendate": item.findtext("pubDate"),
                "via": "Google News",
            }
        )
    return results


def find_related_news(keyword: str, center_date, window_days: int = 3, max_results: int = 5) -> list[dict]:
    start = (center_date - timedelta(days=window_days)).strftime("%Y%m%d%H%M%S")
    end = (center_date + timedelta(days=window_days)).strftime("%Y%m%d%H%M%S")

    gdelt_error = None
    gdelt_results = []
    try:
        gdelt_results = _search_gdelt(keyword, start, end, max_results)
    except RuntimeError as e:
        gdelt_error = str(e)

    # Fall back to (or supplement with) Google News RSS if GDELT failed
    # outright, or came back empty — a date-scoped search can legitimately
    # miss things a relevance-ranked one finds, and vice versa.
    news_results = []
    if not gdelt_results:
        try:
            news_results = _search_google_news_rss(keyword, max_results)
        except RuntimeError as news_error:
            if gdelt_error:
                raise RuntimeError(f"Both sources failed — GDELT: {gdelt_error}; Google News: {news_error}")
            # GDELT succeeded but empty, and the fallback also failed: not
            # a hard error, just report the empty GDELT result honestly.

    combined = gdelt_results + news_results
    seen_titles = set()
    deduped = []
    for article in combined:
        if article["title"] in seen_titles:
            continue
        seen_titles.add(article["title"])
        deduped.append(article)
    return deduped
