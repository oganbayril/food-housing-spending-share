"""Compare Eurostat's two versions of household consumption by purpose.

- nama_10_co3_p3: COICOP 1999 classification (older)
- nama_10_cp18:   COICOP 2018 classification (newer)

Questions:
1. Which countries and years does each version cover?
2. Where both have data, how different are the food and housing shares?
3. Are there suspicious series, e.g. shares that stay exactly the same for
   many years (a sign of estimated back-data rather than measured data)?

Run from the project root:
    uv run python src/investigate_coicop_versions.py
"""

import pandas as pd

from country_codes import EUROSTAT_AGGREGATES
from sources import download_eurostat, save_check


def compute_shares(raw, coicop_column):
    """Food and housing shares per country and year, from one dataset."""
    df = raw[raw["unit"] == "CP_MNAC"]
    df = df[~df["geo"].isin(EUROSTAT_AGGREGATES)]

    # One row per country-year, one column per COICOP item.
    wide = df.pivot_table(
        index=["geo", "TIME_PERIOD"], columns=coicop_column, values="OBS_VALUE"
    )
    wide = wide.reset_index()

    result = pd.DataFrame()
    result["geo"] = wide["geo"]
    result["year"] = wide["TIME_PERIOD"]
    result["food_share"] = wide["CP01"] / wide["TOTAL"] * 100
    result["housing_share"] = wide["CP04"] / wide["TOTAL"] * 100
    # A country-year only counts as covered if both shares can be computed.
    result = result.dropna(subset=["food_share", "housing_share"])
    return result


def coverage(shares):
    """First year, last year and number of years per country."""
    grouped = shares.groupby("geo")["year"]
    table = pd.DataFrame(
        {
            "first_year": grouped.min(),
            "last_year": grouped.max(),
            "n_years": grouped.count(),
        }
    )
    return table


def find_frozen_shares(shares, label):
    """Report countries where both shares repeat exactly from year to year.

    Real spending patterns always move a little. Identical shares (to two
    decimals) for several years in a row suggest the back-data was estimated
    by holding the spending structure fixed.
    """
    for geo, group in shares.groupby("geo"):
        group = group.sort_values("year")
        food = group["food_share"].round(2)
        housing = group["housing_share"].round(2)
        unchanged = (food.diff() == 0) & (housing.diff() == 0)
        if unchanged.sum() >= 2:
            years = group.loc[unchanged, "year"]
            first = years.min() - 1  # the year before the first repeat
            print(
                f"  {label}: {geo} has identical shares in "
                f"{unchanged.sum() + 1} consecutive years ({first}-{years.max()})"
            )


def main():
    raw_99 = download_eurostat(
        "nama_10_co3_p3", "A.CP_MNAC.TOTAL+CP01+CP04.", "nama_10_co3_p3_all.csv"
    )
    raw_18 = download_eurostat(
        "nama_10_cp18", "A.CP_MNAC.TOTAL+CP01+CP04.", "nama_10_cp18_all.csv"
    )

    shares_99 = compute_shares(raw_99, "coicop")
    shares_18 = compute_shares(raw_18, "coicop18")

    # 1. Coverage side by side.
    cov = coverage(shares_99).join(
        coverage(shares_18), how="outer", lsuffix="_1999", rsuffix="_2018"
    )
    cov = cov.reset_index()
    print("\nCoverage (country-years with both shares):")
    print(cov.to_string(index=False))
    save_check(cov, "coicop_versions_coverage.csv")

    # 2. Differences where both versions have the same country and year.
    both = shares_99.merge(shares_18, on=["geo", "year"], suffixes=("_1999", "_2018"))
    both["food_gap"] = both["food_share_2018"] - both["food_share_1999"]
    both["housing_gap"] = both["housing_share_2018"] - both["housing_share_1999"]
    save_check(both, "coicop_versions_overlap.csv")

    print(f"\nOverlapping country-years: {len(both)}")
    for column in ["food_gap", "housing_gap"]:
        size = both[column].abs()
        print(
            f"  {column} (percentage points, absolute): "
            f"median {size.median():.2f}, 90th percentile {size.quantile(0.9):.2f}, "
            f"max {size.max():.2f}"
        )

    print("\nLargest absolute gap per country (percentage points):")
    per_country = both.groupby("geo")[["food_gap", "housing_gap"]].agg(
        lambda gaps: gaps.abs().max()
    )
    per_country = per_country.sort_values("housing_gap", ascending=False)
    print(per_country.round(2).to_string())

    # 3. Frozen shares.
    print("\nSeries with frozen shares:")
    find_frozen_shares(shares_99, "COICOP 1999")
    find_frozen_shares(shares_18, "COICOP 2018")

    # Series breaks are flagged "b" by Eurostat.
    for label, raw in [("COICOP 1999", raw_99), ("COICOP 2018", raw_18)]:
        breaks = raw[raw["OBS_FLAG"] == "b"]
        breaks = breaks[["geo", "TIME_PERIOD"]].drop_duplicates()
        print(f"\nBreaks in series ({label}):")
        if len(breaks) == 0:
            print("  none")
        else:
            print(breaks.to_string(index=False))


if __name__ == "__main__":
    main()
