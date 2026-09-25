"""Turns raw interest-over-time numbers into a one-line, human summary,
and separately flags whether there's a spike worth investigating.

This is deliberately simple arithmetic for now, not an LLM call — the idea
is to get a real signal flowing end-to-end first. Later slices will swap
this kind of function for an actual reasoning agent.
"""

import pandas as pd

RECENT_WINDOW_DAYS = 14  # how far back counts as "recent" vs "earlier in window"
SPIKE_RATIO = 1.5  # peak must be this many times the endpoint baseline
SPIKE_MIN_VALUE = 30  # ...and at least this high on the 0-100 scale, to ignore noise


def detect_spike(df: pd.DataFrame, keyword: str) -> dict:
    """Looks at the whole series (not just first/last day) for a real spike."""
    series = df[keyword]
    peak_value = series.max()
    peak_date = series.idxmax()
    first_value = series.iloc[0]
    last_value = series.iloc[-1]
    baseline = max(first_value, last_value, 1)
    window_end = series.index.max()

    is_recent = (window_end - peak_date).days <= RECENT_WINDOW_DAYS
    is_significant = peak_value >= baseline * SPIKE_RATIO and peak_value >= SPIKE_MIN_VALUE

    return {
        "peak_value": peak_value,
        "peak_date": peak_date,
        "first_value": first_value,
        "last_value": last_value,
        "is_recent": is_recent,
        "is_significant": is_significant,
        "period_start": series.index.min(),
        "period_end": window_end,
    }


def _period_label(spike: dict) -> str:
    start, end = spike["period_start"], spike["period_end"]
    days = (end - start).days
    return f"over the last {days} days ({start:%b %d} - {end:%b %d, %Y})"


def summarize_interest(keyword: str, geo_label: str, spike: dict) -> str:
    first_value = spike["first_value"]
    last_value = spike["last_value"]
    peak_value = spike["peak_value"]
    period = _period_label(spike)

    if peak_value == 0:
        return f"No measurable search interest in '{keyword}' in {geo_label} {period}."

    spike_note = ""
    if spike["is_significant"]:
        when = "recently" if spike["is_recent"] else "earlier in this period"
        peak_date_str = spike["peak_date"].strftime("%b %d, %Y")
        spike_note = f" It spiked to {peak_value} {when}, around {peak_date_str}."

    if first_value == 0:
        trend = f"has risen to {last_value}" if last_value > 0 else "has stayed near zero"
        return f"Interest in '{keyword}' in {geo_label} {trend} {period}.{spike_note}"

    pct_change = (last_value - first_value) / first_value * 100
    direction = "up" if pct_change > 0 else "down" if pct_change < 0 else "flat"

    if direction == "flat":
        return f"Interest in '{keyword}' in {geo_label} has stayed flat {period}.{spike_note}"

    return (
        f"Interest in '{keyword}' in {geo_label} is {direction} "
        f"{abs(pct_change):.0f}% {period} "
        f"(from {first_value} to {last_value} on Google's 0-100 scale).{spike_note}"
    )
