"""Compare Eurostat and OECD shares for countries published by both.

Every country on the map uses ONE source. This check shows whether the two
sources agree where they overlap, and how many extra years the OECD has
beyond Eurostat's last year (e.g. the UK after 2019). It does not change any
data: whether to use the OECD for those extra years is a separate decision.

Comparisons are made within the same COICOP version where the OECD has it
(like with like). The OECD's other version is reported too.

Also compares the OECD's two COICOP versions for the OECD-sourced countries
that appear in both (the OECD side of the version-gap check).

Run from the project root, after src/load_eurostat.py:
    uv run python src/compare_eurostat_oecd.py
"""

import pandas as pd

from country_codes import OECD_MEMBERS_ISO3
from load_oecd import download_version
from shares import compute_shares
from sources import PROCESSED_DIR, save_check

ROUNDING = 0.05  # percentage points; differences up to this count as a match


def oecd_shares_all_countries(data, version):
    """Shares for every OECD member in one OECD version."""
    data = data[data["country_code"].isin(OECD_MEMBERS_ISO3)]
    iso3_lookup = {}
    for country in data["country_code"].unique():
        iso3_lookup[country] = country
    shares = compute_shares(data, "OECD", iso3_lookup)
    shares = shares[["iso3", "year", "coicop", "share_pct"]]
    shares = shares.rename(columns={"share_pct": f"oecd_{version}"})
    return shares


def summarise(compared, column):
    """Per country: how many years overlap and how far apart the shares are."""
    rows = []
    for iso3, group in compared.groupby("iso3"):
        both = group.dropna(subset=["share_pct", column])
        if len(both) == 0:
            continue
        gaps = (both[column] - both["share_pct"]).abs()
        food = gaps[both["coicop"] == "CP01"]
        housing = gaps[both["coicop"] == "CP04"]
        rows.append(
            {
                "iso3": iso3,
                # str(): read from CSV the version is a number, but the
                # OECD version below is text; both must be text to compare.
                "eurostat_version": str(group["coicop_version"].iloc[0]),
                "oecd_version": column.replace("oecd_", ""),
                "overlap_years": both["year"].nunique(),
                "food_median_gap": round(food.median(), 2),
                "food_max_gap": round(food.max(), 2),
                "housing_median_gap": round(housing.median(), 2),
                "housing_max_gap": round(housing.max(), 2),
                "match_within_rounding": bool(gaps.max() <= ROUNDING),
            }
        )
    return pd.DataFrame(rows)


def extra_oecd_years(eurostat, oecd):
    """Years with an OECD share after the country's last Eurostat share."""
    rows = []
    for iso3, group in eurostat.groupby("iso3"):
        available = group.dropna(subset=["share_pct"])
        if len(available) == 0:
            continue
        last_eurostat = available["year"].max()
        for version in ["2018", "1999"]:
            column = f"oecd_{version}"
            later = oecd[(oecd["iso3"] == iso3) & (oecd["year"] > last_eurostat)]
            later = later.dropna(subset=[column])
            if len(later) > 0:
                rows.append(
                    {
                        "iso3": iso3,
                        "last_eurostat_year": last_eurostat,
                        "oecd_version": version,
                        "extra_years": f"{later['year'].min()}-{later['year'].max()}",
                    }
                )
    return pd.DataFrame(rows)


def main():
    eurostat = pd.read_csv(PROCESSED_DIR / "eurostat_shares.csv")
    eurostat = eurostat[eurostat["iso3"].isin(OECD_MEMBERS_ISO3)]

    oecd_2018 = oecd_shares_all_countries(download_version("2018"), "2018")
    oecd_1999 = oecd_shares_all_countries(download_version("1999"), "1999")
    oecd = oecd_2018.merge(oecd_1999, on=["iso3", "year", "coicop"], how="outer")

    compared = eurostat.merge(oecd, on=["iso3", "year", "coicop"], how="left")

    summary = pd.concat(
        [summarise(compared, "oecd_2018"), summarise(compared, "oecd_1999")],
        ignore_index=True,
    )
    summary["same_version"] = summary["eurostat_version"] == summary["oecd_version"]
    summary = summary.sort_values(["iso3", "same_version"], ascending=[True, False])
    save_check(summary, "eurostat_vs_oecd.csv")

    print("\nEurostat vs OECD, same COICOP version (percentage points):")
    same = summary[summary["same_version"]].drop(columns="same_version")
    print(same.to_string(index=False))

    no_same = sorted(set(eurostat["iso3"]) - set(same["iso3"]))
    print(f"\nNo same-version OECD data to compare: {', '.join(no_same)}")

    print("\nEurostat vs OECD, other COICOP version (for reference):")
    other = summary[~summary["same_version"]].drop(columns="same_version")
    print(other.to_string(index=False))

    extra = extra_oecd_years(eurostat, oecd)
    save_check(extra, "oecd_extra_years.csv")
    print("\nOECD years beyond the last Eurostat year:")
    print(extra.to_string(index=False))

    # OECD's own version gap, for OECD-sourced countries in both versions.
    oecd_sourced = pd.read_csv(PROCESSED_DIR / "oecd_shares.csv")["iso3"].unique()
    both_versions = oecd[oecd["iso3"].isin(oecd_sourced)]
    both_versions = both_versions.dropna(subset=["oecd_2018", "oecd_1999"]).copy()
    both_versions["gap"] = both_versions["oecd_2018"] - both_versions["oecd_1999"]
    save_check(both_versions, "oecd_versions_overlap.csv")
    print("\nOECD 1999 vs 2018, OECD-sourced countries in both versions:")
    for (iso3, coicop), group in both_versions.groupby(["iso3", "coicop"]):
        size = group["gap"].abs()
        print(
            f"  {iso3} {coicop}: {len(group)} years, median {size.median():.2f}, "
            f"max {size.max():.2f} pts"
        )


if __name__ == "__main__":
    main()
