"""Guesses a likely shipping chokepoint/route for a source country.

This is a geography-based heuristic, not verified per-shipment routing —
no free API tells us the actual sea lane a specific cargo took. Treat
this as "worth checking," not "confirmed route."
"""

# Country name (as returned by UN Comtrade's partnerDesc) -> region key.
COUNTRY_REGION = {
    "Iraq": "gulf", "Saudi Arabia": "gulf", "United Arab Emirates": "gulf",
    "Kuwait": "gulf", "Qatar": "gulf", "Oman": "gulf", "Bahrain": "gulf", "Iran": "gulf",
    "Nigeria": "west_africa", "Angola": "west_africa", "Ghana": "west_africa",
    "Russian Federation": "russia", "Ukraine": "black_sea", "Romania": "black_sea",
    "Bulgaria": "black_sea", "Turkiye": "black_sea", "Turkey": "black_sea",
    "USA": "north_america", "United States": "north_america", "Canada": "north_america",
    "Mexico": "north_america",
    "Brazil": "south_america", "Argentina": "south_america", "Chile": "south_america",
    "Peru": "south_america", "Colombia": "south_america",
    "Indonesia": "southeast_asia", "Malaysia": "southeast_asia", "Singapore": "southeast_asia",
    "Vietnam": "southeast_asia", "Thailand": "southeast_asia", "Philippines": "southeast_asia",
    "China": "east_asia", "Japan": "east_asia", "Rep. of Korea": "east_asia",
    "South Korea": "east_asia", "Taiwan": "east_asia",
    "Germany": "europe", "Netherlands": "europe", "France": "europe", "Belgium": "europe",
    "Spain": "europe", "Italy": "europe",
    "Australia": "oceania",
    "South Africa": "southern_africa",
}

REGION_CHOKEPOINTS = {
    "gulf": ["Strait of Hormuz"],
    # Russian oil routing is uncertain under sanctions — both are plausible,
    # see ROUTING_NOTES below for the caveat rather than baking it into the name.
    "russia": ["Suez Canal", "Cape of Good Hope"],
    "west_africa": ["Gulf of Guinea", "Cape of Good Hope"],
    "black_sea": ["Bosphorus Strait", "Black Sea grain corridor"],
    "north_america": ["Panama Canal"],
    "south_america": ["Panama Canal"],
    "southeast_asia": ["Strait of Malacca"],
    "east_asia": ["Strait of Malacca", "Taiwan Strait"],
    "europe": ["Suez Canal", "English Channel / North Sea lanes"],
    "oceania": ["Lombok Strait", "Strait of Malacca"],
    "southern_africa": ["Cape of Good Hope"],
}


ROUTING_NOTES = {
    "russia": "Routing for Russian exports has been unsettled since 2022-era sanctions "
    "rerouted much of its oil trade — treat both listed chokepoints as plausible, not certain.",
}

# Structural (not live) lead-time notes: how a route TYPICALLY compares to
# alternatives, based on geography/distance — independent of today's real
# transit-volume status (see chokepoint_status.py for that). Only includes
# a specific day-range where it's a well-established, widely-reported
# industry figure (verified via web search, not invented); otherwise stays
# qualitative rather than faking precision.
LEAD_TIME_NOTES = {
    "Cape of Good Hope": "Typically adds roughly 10-15+ days versus a Suez-routed "
    "alternative (industry-reported range ~7-25 days depending on the specific lane) "
    "due to the much longer distance around Africa.",
    "Suez Canal": "Historically the shortest standard route between the Middle East/Asia "
    "and Europe, when open and unaffected by regional conflict.",
    "Panama Canal": "Standard shortest route between the Americas' two coasts and "
    "onward to Asia/Europe; no verified alternative-route day-count available here.",
    "Strait of Malacca": "Standard shortest route between the Indian Ocean and East "
    "Asia/Pacific; the main alternative (Lombok/Sunda Straits) is a minor detour, not "
    "a major reroute.",
}


def get_likely_chokepoints(country: str) -> list[str]:
    region = COUNTRY_REGION.get(country)
    if not region:
        return []
    return REGION_CHOKEPOINTS.get(region, [])


def get_routing_note(country: str) -> str | None:
    region = COUNTRY_REGION.get(country)
    return ROUTING_NOTES.get(region) if region else None


def get_lead_time_note(chokepoint: str) -> str | None:
    return LEAD_TIME_NOTES.get(chokepoint)
