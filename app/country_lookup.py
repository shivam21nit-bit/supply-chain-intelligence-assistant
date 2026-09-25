"""Resolves free-text country names (as typed into the supply chain
graph, e.g. "India", "Saudi Arabia") to ISO3 codes (e.g. "IND", "SAU"),
since your graph stores country as free text but UN Comtrade needs a
standard code. Uses `pycountry` — free, offline, standard ISO name/code
data, no API call involved.
"""

import pycountry


def resolve_iso3(name: str) -> str | None:
    """Returns the ISO3 code, or None if it can't be confidently resolved
    (caller should show an honest 'couldn't resolve this country' message
    rather than guessing)."""
    if not name:
        return None

    exact = pycountry.countries.get(name=name)
    if exact:
        return exact.alpha_3

    try:
        matches = pycountry.countries.search_fuzzy(name)
    except LookupError:
        return None

    return matches[0].alpha_3 if matches else None
