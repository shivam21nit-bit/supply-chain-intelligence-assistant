"""Real (if noisy) 'is this chokepoint currently busy or quiet' signal,
from IMF PortWatch's free, public, no-signup dataset of satellite
AIS-derived daily vessel transit-call counts for 28 major maritime
chokepoints (https://portwatch.imf.org).

Honesty check on what this actually is: daily counts here are small
(single digits to low tens) and noisy day-to-day — this looks like a
partial-coverage sample, not a full vessel census. We compare a trailing
7-day average against a 35-day baseline rather than trusting any single
day, but this is still a rough signal, not a precise measurement — treat
a modest swing as "worth a look," not proof of disruption.
"""

import requests

PORTWATCH_API = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)

# Our chokepoints.py names -> PortWatch's exact portname spelling, where
# they differ. Anything not covering one of PortWatch's 28 tracked
# chokepoints (verified live: Bab el-Mandeb, Balabac, Bering, Bohai,
# Bosporus, Cape of Good Hope, Dover, Gibraltar, Kerch, Korea, Lombok,
# Luzon, Magellan, Makassar, Malacca, Mindoro, Mona, Ombai, Oresund,
# Panama, Hormuz, Suez, Sunda, Taiwan, Torres, Tsugaru, Windward,
# Yucatan) honestly reports "not tracked" rather than guessing.
NAME_ALIASES = {
    "Strait of Malacca": "Malacca Strait",
    "Bosphorus Strait": "Bosporus Strait",
    "English Channel / North Sea lanes": "Dover Strait",
}


def get_chokepoint_status(chokepoint_name: str, recent_days: int = 7, baseline_days: int = 35) -> dict:
    """Raises ValueError if this chokepoint isn't one PortWatch tracks,
    RuntimeError if the request itself fails."""
    portwatch_name = NAME_ALIASES.get(chokepoint_name, chokepoint_name)

    try:
        response = requests.get(
            PORTWATCH_API,
            params={
                "where": f"portname='{portwatch_name}'",
                "outFields": "date,n_total",
                "orderByFields": "date DESC",
                "resultRecordCount": baseline_days,
                "f": "json",
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        raise RuntimeError(f"PortWatch request failed ({e.__class__.__name__}): {e}")

    if "error" in data:
        raise RuntimeError(f"PortWatch API error: {data['error']}")

    features = data.get("features", [])
    if not features:
        raise ValueError(
            f"'{chokepoint_name}' isn't one of PortWatch's 28 tracked chokepoints — "
            "no real-time transit data available for it."
        )

    counts = [f["attributes"]["n_total"] for f in features]
    recent = counts[:recent_days]
    recent_avg = sum(recent) / len(recent)
    baseline_avg = sum(counts) / len(counts)
    pct_change = ((recent_avg - baseline_avg) / baseline_avg * 100) if baseline_avg else None

    return {
        "chokepoint": portwatch_name,
        "recent_avg_daily_transits": round(recent_avg, 1),
        "baseline_avg_daily_transits": round(baseline_avg, 1),
        "pct_change": round(pct_change, 1) if pct_change is not None else None,
        "as_of_date": features[0]["attributes"]["date"],
        "recent_days": recent_days,
        "baseline_days": baseline_days,
    }
