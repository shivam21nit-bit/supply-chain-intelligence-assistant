"""Keyword -> likely-effect heuristic for tagging news headlines.

Deliberately simple, same spirit as demand_signal's spike detection:
explainable rules rather than a verified judgment. If a headline matches
none of these, we say so honestly instead of guessing.
"""

KEYWORD_EFFECTS = {
    "strike": "delivery delay",
    "blockade": "delivery delay",
    "closure": "delivery delay",
    "closed": "delivery delay",
    "congestion": "delivery delay",
    "attack": "delivery delay / safety risk",
    "conflict": "delivery delay / safety risk",
    "war": "delivery delay / safety risk",
    "sanctions": "availability / price",
    "export ban": "availability / price",
    "tariff": "price",
    "drought": "availability / price",
    "flood": "availability / delivery delay",
    "wildfire": "availability",
    "shortage": "availability / price",
    "grounded": "delivery delay",
    "tension": "delivery delay / safety risk",
    "risk": "delivery delay / safety risk",
    "houthi": "delivery delay / safety risk",
    "disruption": "delivery delay",
    "delay": "delivery delay",
}


def tag_effect(title: str) -> str | None:
    lowered = title.lower()
    for keyword, effect in KEYWORD_EFFECTS.items():
        if keyword in lowered:
            return effect
    return None
