"""Fetches real bilateral import data from the UN Comtrade API.

This replaces guesswork about "who exports X to country Y" with actual
trade statistics. Requires a free API key (see .env / UNCOMTRADE_API_KEY),
which you register for yourself at https://uncomtrade.org — this code
only reads the key from the environment, never hardcodes or prints it.
"""

import os

import comtradeapicall
from dotenv import load_dotenv

load_dotenv()

# UN Comtrade's most recent full year of data usually lags 1-2 years behind
# today. We try the most likely recent years first and fall back if empty.
CANDIDATE_YEARS = ["2024", "2023", "2022"]


def get_top_import_sources(hs_code: str, destination_iso3: str, top_n: int = 5) -> dict:
    """Returns {"year": ..., "sources": [{"country": ..., "value_usd": ..., "share_pct": ...}]}

    Raises ValueError if no data could be found for any candidate year.
    """
    api_key = os.environ.get("UNCOMTRADE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "UNCOMTRADE_API_KEY not found. Make sure disruption_feed/.env exists "
            "with a valid key."
        )

    reporter_code = comtradeapicall.convertCountryIso3ToCode(destination_iso3.upper())
    if not reporter_code:
        raise ValueError(f"Unrecognized destination country code: '{destination_iso3}'")

    for year in CANDIDATE_YEARS:
        df = comtradeapicall.getFinalData(
            api_key,
            typeCode="C",
            freqCode="A",
            clCode="HS",
            period=year,
            reporterCode=reporter_code,
            cmdCode=hs_code,
            flowCode="M",  # imports
            partnerCode=None,
            partner2Code=None,
            customsCode=None,
            motCode=None,
            maxRecords=250,
            format_output="JSON",
            aggregateBy=None,
            breakdownMode="classic",
            countOnly=None,
            includeDesc=True,
        )

        if df is None or df.empty:
            continue

        world_row = df[df["partnerDesc"] == "World"]
        world_total = world_row["primaryValue"].iloc[0] if not world_row.empty else None

        partners = df[df["partnerDesc"] != "World"].sort_values("primaryValue", ascending=False)
        if partners.empty:
            continue

        sources = []
        for _, row in partners.head(top_n).iterrows():
            value = row["primaryValue"]
            share_pct = (value / world_total * 100) if world_total else None
            net_wgt = row.get("netWgt")
            # Customs value per kg — a rough relative-cost proxy across
            # sources for the *same* item, not a delivered/logistics cost.
            unit_value_per_kg = (value / net_wgt) if net_wgt and net_wgt > 0 else None
            sources.append(
                {
                    "country": row["partnerDesc"],
                    "iso3": row.get("partnerISO"),
                    "value_usd": value,
                    "share_pct": share_pct,
                    "unit_value_per_kg": unit_value_per_kg,
                }
            )

        return {"year": year, "sources": sources}

    raise ValueError(
        f"No UN Comtrade import data found for HS code {hs_code} into {destination_iso3} "
        f"in years {CANDIDATE_YEARS}."
    )
