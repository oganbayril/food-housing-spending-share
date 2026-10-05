"""Combine the Eurostat and OECD shares into one file for the map.

Every country must come from exactly one source (sources are never mixed
within a country). This script stops with an error if that is ever violated.

Run from the project root, after src/load_eurostat.py and src/load_oecd.py:
    uv run python src/combine_sources.py
"""

import pandas as pd

from sources import PROCESSED_DIR


def main():
    eurostat = pd.read_csv(PROCESSED_DIR / "eurostat_shares.csv")
    oecd = pd.read_csv(PROCESSED_DIR / "oecd_shares.csv")

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
