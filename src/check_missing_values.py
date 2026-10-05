"""Count missing country-years in the processed Eurostat shares.

Run this before any plotting: a map silently shows missing countries as
blank, which is easy to misread as "no problem" or overlook entirely.

A country-year counts as missing if the food or the housing share cannot be
shown. The reason is recorded:
- "not published":    Eurostat has no total or category value for that year
- "frozen back-data": published, but treated as missing (see decisions.py)

Only years from 1995 on are counted (the map's time range).

Run from the project root, after src/load_eurostat.py:
    uv run python src/check_missing_values.py
"""

import pandas as pd

from sources import PROCESSED_DIR, save_check

FIRST_YEAR = 1995


def missing_reason(row):
    if row["frozen_back_data"]:
        return "frozen back-data"
    return "not published"


def main():
    shares = pd.read_csv(PROCESSED_DIR / "eurostat_shares.csv")
    shares = shares[shares["year"] >= FIRST_YEAR]
    last_year = shares["year"].max()

    # One row per country-year: shown only if BOTH shares exist.
    wide = shares.pivot_table(
        index=["country_code", "year"],
        columns="coicop",
        values="share_pct",
        dropna=False,
    )
    wide = wide.reset_index()
    frozen = shares[shares["coicop"] == "CP01"][["country_code", "year", "frozen_back_data"]]
    wide = wide.merge(frozen, on=["country_code", "year"])
    wide["missing"] = wide["CP01"].isna() | wide["CP04"].isna()

    missing = wide[wide["missing"]].copy()
    missing["reason"] = missing.apply(missing_reason, axis=1)

    n_countries = wide["country_code"].nunique()
    print(f"Grid: {n_countries} countries x {FIRST_YEAR}-{last_year} = {len(wide)} country-years")
    print(f"Missing: {len(missing)} ({len(missing) / len(wide) * 100:.1f}%)")
    print(missing["reason"].value_counts().to_string())

    # Per country: available range, and any gaps INSIDE that range (the most
    # worrying kind, because they break a series that otherwise exists).
    rows = []
    for country, group in wide.groupby("country_code"):
        available = group[~group["missing"]]["year"]
        if len(available) == 0:
            rows.append({"country_code": country, "first": None, "last": None,
                         "n_available": 0, "n_missing": len(group), "interior_gaps": ""})
            continue
        first = available.min()
        last = available.max()
        inside = group[(group["year"] > first) & (group["year"] < last)]
        gaps = inside[inside["missing"]]["year"].tolist()
        rows.append(
            {
                "country_code": country,
                "first": first,
                "last": last,
                "n_available": len(available),
                "n_missing": int(group["missing"].sum()),
                "interior_gaps": ", ".join(str(year) for year in gaps),
            }
        )
    per_country = pd.DataFrame(rows)
    print("\nPer country (from 1995):")
    print(per_country.to_string(index=False))

    # Per year: how many countries can be shown. Matters most for the latest
    # years, where the map would otherwise look complete when it is not.
    per_year = wide.groupby("year")["missing"].agg(["size", "sum"])
    per_year = per_year.rename(columns={"size": "countries", "sum": "missing"})
    per_year["available"] = per_year["countries"] - per_year["missing"]
    per_year = per_year.reset_index()
    print("\nPer year:")
    print(per_year.to_string(index=False))

    # Imputed rent is needed for the housing hover.
    housing = shares[(shares["coicop"] == "CP04") & shares["share_pct"].notna()]
    no_imputed = housing[housing["imputed_rent_share_pct"].isna()]
    counts = no_imputed.groupby("country_code").size()
    print("\nHousing shares without an imputed-rent figure (country: years):")
    print(counts.to_string() if len(counts) > 0 else "  none")

    save_check(per_country, "missing_by_country.csv")
    save_check(per_year, "missing_by_year.csv")


if __name__ == "__main__":
    main()
