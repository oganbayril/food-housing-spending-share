"""Combine the Eurostat and OECD shares into one file for the map.

Every country comes from exactly one source (sources are never mixed within
a country). By default that is Eurostat; decisions.SOURCE_OVERRIDES moves a
country's whole series to the OECD (the UK). eurostat_shares.csv still
contains those countries, so the two sources can be compared; they are
dropped here. The script stops with an error if a country ends up in both.

Run from the project root, after src/load_eurostat.py and src/load_oecd.py:
    uv run python src/combine_sources.py
"""

import pandas as pd

from decisions import SOURCE_OVERRIDES
from sources import PROCESSED_DIR


def main():
    eurostat = pd.read_csv(PROCESSED_DIR / "eurostat_shares.csv")
    oecd = pd.read_csv(PROCESSED_DIR / "oecd_shares.csv")

    moved = []
    for iso3, source in SOURCE_OVERRIDES.items():
        if source == "OECD":
            moved.append(iso3)
    eurostat = eurostat[~eurostat["iso3"].isin(moved)]
    print(f"Taken from the OECD instead of Eurostat: {', '.join(moved)}")

    in_both = set(eurostat["iso3"]) & set(oecd["iso3"])
    if in_both:
        raise ValueError(f"Countries in both sources: {sorted(in_both)}")

    combined = pd.concat([eurostat, oecd], ignore_index=True)
    combined = combined.sort_values(["iso3", "year", "coicop"])

    path = PROCESSED_DIR / "shares.csv"
    combined.to_csv(path, index=False)

    countries = combined.groupby("source")["iso3"].nunique()
    print(f"Saved {len(combined)} rows to {path}")
    print(countries.to_string())


if __name__ == "__main__":
    main()
