"""Searches for recent news near a shipping chokepoint.

Tries two independent free sources, since relying on just one means a
single rate-limit hit kills disruption detection entirely:

1. GDELT Doc API — no signup, no key, precise "last N days" search, but
   rate-limits to ~1 request/5s and can stay stubborn under sustained use.
2. Google News RSS — no signup, no key, no documented rate limit, but
   only surfaces currently-indexed/recent-ish articles, not a true
   historical window — a real fallback, not a like-for-like replacement.
"""

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from disruption_keywords import tag_effect

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def _get_with_retry(params: dict, attempts: int = 3, backoff_seconds: int = 15):
    """GDELT rate-limits to ~1 request/5s and can stay grumpy for longer than
    that after repeated hits, so we back off and retry a couple of times
    rather than immediately reporting failure."""
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(GDELT_DOC_API, params=params, timeout=30)
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


def _search_gdelt(query: str, window_days: int, max_results: int) -> list[dict]:
    end = datetime.utcnow()
    start = end - timedelta(days=window_days)

    # GDELT parses unquoted multi-word queries word-by-word and rejects short
    # words like "of" as a keyword on its own — quoting forces an exact-phrase
    # match instead, which is also more precise for named locations anyway.
    params = {
        "query": f'"{query}"',
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_results,
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
        "sort": "HybridRel",
    }

    response = _get_with_retry(params)

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"GDELT returned a non-JSON response: {response.text[:200]!r}")

    articles = data.get("articles", [])
    return [
        {"title": a.get("title"), "url": a.get("url"), "source": a.get("domain"),
         "seendate": a.get("seendate"), "via": "GDELT"}
        for a in articles
        if a.get("title")
    ]


def _search_google_news_rss(query: str, max_results: int) -> list[dict]:
    try:
        response = requests.get(
            GOOGLE_NEWS_RSS,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
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
            {"title": title, "url": item.findtext("link"),
             "source": source_el.text if source_el is not None else None,
             "seendate": item.findtext("pubDate"), "via": "Google News"}
        )
    return results


def search_recent_news(query: str, window_days: int = 21, max_results: int = 5) -> list[dict]:
    gdelt_error = None
    gdelt_results = []
    try:
        gdelt_results = _search_gdelt(query, window_days, max_results)
    except RuntimeError as e:
        gdelt_error = str(e)

    news_results = []
    if not gdelt_results:
        try:
            news_results = _search_google_news_rss(query, max_results)
        except RuntimeError as news_error:
            if gdelt_error:
                raise RuntimeError(f"Both sources failed — GDELT: {gdelt_error}; Google News: {news_error}")

    combined = gdelt_results + news_results
    seen_titles = set()
    deduped = []
    for article in combined:
        if article["title"] in seen_titles:
            continue
        seen_titles.add(article["title"])
        article["effect"] = tag_effect(article["title"])
        deduped.append(article)
    return deduped
