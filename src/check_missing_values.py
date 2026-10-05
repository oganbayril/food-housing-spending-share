"""Count missing country-years in the combined shares (data/processed/shares.csv).

Run this before any plotting: a map silently shows missing countries as
blank, which is easy to misread or overlook.

A country-year counts as missing if the food or the housing share cannot be
shown. The reason is recorded:
- "not published":    the source has no total or category value for that year
- "frozen back-data": published, but treated as missing (see decisions.py)

Only the map's years are counted: 1995 to 2024 (decisions.py).

Run from the project root, after src/combine_sources.py:
    uv run python src/check_missing_values.py
"""

import pandas as pd

from decisions import FIRST_YEAR, MAP_LAST_YEAR
from sources import PROCESSED_DIR, save_check


def missing_reason(row):
    if row["frozen_back_data"]:
        return "frozen back-data"
    return "not published"


def build_country_years(shares):
    """One row per country-year with both shares side by side."""
    # dropna=False keeps country-years where a share is empty. "source" is
    # NOT in the index: pivot_table would then pair every source with every
    # country and invent rows like "Eurostat, Australia". It is added below.
    wide = shares.pivot_table(
        index=["iso3", "year"],
        columns="coicop",
        values="share_pct",
        dropna=False,
    )
    wide = wide.reset_index()
    context = shares[shares["coicop"] == "CP01"]
    context = context[["iso3", "year", "source", "frozen_back_data"]]
    wide = wide.merge(context, on=["iso3", "year"])
    wide["missing"] = wide["CP01"].isna() | wide["CP04"].isna()
    return wide


def per_country_table(wide):
    """Available range per country, and any gaps INSIDE that range (the most
    worrying kind, because they break a series that otherwise exists)."""
    rows = []
    for (source, iso3), group in wide.groupby(["source", "iso3"]):
        available = group[~group["missing"]]["year"]
        row = {
            "source": source,
            "iso3": iso3,
            "first": None,
            "last": None,
            "n_available": len(available),
            "n_missing": int(group["missing"].sum()),
            "interior_gaps": "",
        }
        if len(available) > 0:
            row["first"] = available.min()
            row["last"] = available.max()
            inside = group[(group["year"] > row["first"]) & (group["year"] < row["last"])]
            gaps = inside[inside["missing"]]["year"].tolist()
            row["interior_gaps"] = ", ".join(str(year) for year in gaps)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    shares = pd.read_csv(PROCESSED_DIR / "shares.csv")
    shares = shares[(shares["year"] >= FIRST_YEAR) & (shares["year"] <= MAP_LAST_YEAR)]

    wide = build_country_years(shares)
    missing = wide[wide["missing"]].copy()
    missing["reason"] = missing.apply(missing_reason, axis=1)

    n_countries = wide["iso3"].nunique()
    n_years = MAP_LAST_YEAR - FIRST_YEAR + 1
    print(
        f"Grid: {n_countries} countries x {n_years} years ({FIRST_YEAR}-{MAP_LAST_YEAR}) "
        f"= {len(wide)} country-years"
    )
    print(f"Missing: {len(missing)} ({len(missing) / len(wide) * 100:.1f}%)")
    print(missing["reason"].value_counts().to_string())

    per_country = per_country_table(wide)
    print("\nPer country:")
    print(per_country.to_string(index=False))

    # Per year: how many countries can be shown.
    per_year = wide.groupby("year")["missing"].agg(["size", "sum"])
    per_year = per_year.rename(columns={"size": "countries", "sum": "missing"})
    per_year["available"] = per_year["countries"] - per_year["missing"]
    per_year = per_year.reset_index()
    print("\nPer year:")
    print(per_year.to_string(index=False))

    # Imputed rent is needed for the housing hover.
    housing = shares[(shares["coicop"] == "CP04") & shares["share_pct"].notna()]
    no_imputed = housing[housing["imputed_rent_share_pct"].isna()]
    counts = no_imputed.groupby("iso3").size()
    print("\nHousing shares without an imputed-rent figure (country: years):")
    print(counts.to_string() if len(counts) > 0 else "  none")

    save_check(per_country, "missing_by_country.csv")
    save_check(per_year, "missing_by_year.csv")


if __name__ == "__main__":
    main()
