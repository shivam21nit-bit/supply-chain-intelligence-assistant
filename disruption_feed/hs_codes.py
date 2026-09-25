"""Maps plain item names to HS (Harmonized System) commodity codes.

HS codes are the standardized international product codes that trade
statistics are filed under — this is objective, checkable data (not a
guess about who trades with whom, which is the part we get from the real
UN Comtrade API instead).

This is a small, curated starter list. Anything not listed here will
honestly report "not found" rather than fabricate a guess.
"""

HS_CODES = {
    "crude oil": "2709",
    "oil": "2709",
    "petroleum": "2709",
    "natural gas": "2711",
    "lng": "2711",
    "wheat": "1001",
    "rice": "1006",
    "coffee": "0901",
    "cotton": "5201",
    "copper": "7403",
    "palm oil": "1511",
    "semiconductors": "8542",
    "chips": "8542",
    "lithium": "2836",
    "sugar": "1701",
    "soybeans": "1201",
    "coal": "2701",
}


def get_hs_code(item: str) -> str | None:
    return HS_CODES.get(item.strip().lower())
