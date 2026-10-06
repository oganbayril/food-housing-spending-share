"""Share calculation shared by the Eurostat and OECD loaders.

Both loaders first bring their source into the same "long" format, one row
per observation:

    country_code | year | unit | coicop | value | flag | coicop_version

with coicop in TOTAL, CP01, CP04, CP042 and unit "CP_MNAC" (current prices,
millions of national currency) or "PC_TOT" (Eurostat's published share, used
only as a cross-check). Then compute_shares() turns that into the processed
table, so both sources go through exactly the same calculation.
"""

import pandas as pd

from decisions import (
    CATEGORY_LABELS,
    FIRST_YEAR,
    HIGH_TOURISM_ISO3,
    LARGE_VERSION_GAPS,
    NEAR_BOUNDARY_MARGIN,
    TIER_THRESHOLDS,
    is_frozen,
)

UNIT_VALUES = "CP_MNAC"
UNIT_CHECK = "PC_TOT"
TOTAL_CODE = "TOTAL"
IMPUTED_RENT_CODE = "CP042"

COLUMN_ORDER = [
    "source",
    "country_code",
    "iso3",
    "year",
    "coicop_version",
    "coicop",
    "category",
    "spending_mnac",
    "total_mnac",
    "share_pct",
    "essentials_share",
    "near_tier_boundary",
    "imputed_rent_share_pct",
    "eurostat_pc_tot",
    "diff_vs_eurostat",
    "flag",
    "frozen_back_data",
    "high_tourism",
    "large_version_gap_pts",
    "version_gap_note",
]


def build_grid(data):
    """Every country x year x category we expect, so gaps stay visible.

    Years run from 1995 (or a country's first year, if earlier) to the latest
    year in the data. A country-year that the source does not publish becomes
    a row with no values instead of silently not existing.
    """
    last_year = data["year"].max()
    rows = []
    for country, group in data.groupby("country_code"):
        first_year = min(FIRST_YEAR, group["year"].min())
        version = group["coicop_version"].iloc[0]
        for year in range(first_year, last_year + 1):
            for code in CATEGORY_LABELS:
                rows.append(
                    {
                        "country_code": country,
                        "year": year,
                        "coicop_version": version,
                        "coicop": code,
                    }
                )
    return pd.DataFrame(rows)


def compute_shares(data, source, iso3_lookup):
    """One row per country, year and category, with the share and context.

    `source` is "Eurostat" or "OECD". `iso3_lookup` maps the source's country
    codes to ISO-3 (for the OECD they already are ISO-3).
    """
    values = data[data["unit"] == UNIT_VALUES]
    published = data[data["unit"] == UNIT_CHECK]
    keys = ["country_code", "year"]

    totals = values[values["coicop"] == TOTAL_CODE]
    totals = totals[keys + ["value", "flag"]]
    totals = totals.rename(columns={"value": "total_mnac", "flag": "total_flag"})

    imputed = values[values["coicop"] == IMPUTED_RENT_CODE]
    imputed = imputed[keys + ["value"]]
    imputed = imputed.rename(columns={"value": "imputed_rent_mnac"})

    spending = values[values["coicop"].isin(CATEGORY_LABELS.keys())]
    spending = spending[keys + ["coicop", "value", "flag"]]
    spending = spending.rename(columns={"value": "spending_mnac"})

    published = published[published["coicop"].isin(CATEGORY_LABELS.keys())]
    published = published[keys + ["coicop", "value"]]
    published = published.rename(columns={"value": "eurostat_pc_tot"})

    result = build_grid(data)
    result = result.merge(spending, on=keys + ["coicop"], how="left")
    result = result.merge(totals, on=keys, how="left")
    result = result.merge(imputed, on=keys, how="left")
    result = result.merge(published, on=keys + ["coicop"], how="left")

    result["source"] = source
    result["iso3"] = result["country_code"].map(iso3_lookup)
    result["category"] = result["coicop"].map(CATEGORY_LABELS)
    result["share_pct"] = result["spending_mnac"] / result["total_mnac"] * 100

    # Imputed rent as a % of total spending, shown in the housing hover
    # ("of which imputed rent: X%"). Only meaningful on the housing rows.
    imputed_share = result["imputed_rent_mnac"] / result["total_mnac"] * 100
    result["imputed_rent_share_pct"] = imputed_share.where(result["coicop"] == "CP04")

    # A share is provisional/estimated if either the category or the total
    # is, so take the category's flag and fall back to the total's.
    result["flag"] = result["flag"].fillna(result["total_flag"])

    # Essentials share: food + housing & utilities as a % of total spending.
    # It belongs to the country-year, not to one category, so the same value
    # is repeated on the food row and the housing row. min_count=2: if either
    # category is missing, the sum is missing too (not just the other one).
    essentials = result.groupby(["country_code", "year"])["spending_mnac"].sum(min_count=2)
    essentials = essentials.rename("essentials_mnac").reset_index()
    result = result.merge(essentials, on=["country_code", "year"], how="left")
    result["essentials_share"] = result["essentials_mnac"] / result["total_mnac"] * 100

    # Frozen back-data: keep the published values, but no share.
    frozen = []
    for country, year in zip(result["country_code"], result["year"]):
        frozen.append(is_frozen(country, year))
    result["frozen_back_data"] = frozen
    result.loc[result["frozen_back_data"], "share_pct"] = None
    result.loc[result["frozen_back_data"], "imputed_rent_share_pct"] = None
    result.loc[result["frozen_back_data"], "essentials_share"] = None

    # Near a tier boundary: essentials_share within NEAR_BOUNDARY_MARGIN
    # points of a threshold (post-hoc margin, D16). Empty share -> False.
    near = []
    for share in result["essentials_share"]:
        is_near = False
        if pd.notna(share):
            for threshold in TIER_THRESHOLDS:
                if abs(share - threshold) <= NEAR_BOUNDARY_MARGIN:
                    is_near = True
        near.append(is_near)
    result["near_tier_boundary"] = near

    result["diff_vs_eurostat"] = result["share_pct"] - result["eurostat_pc_tot"]
    result["high_tourism"] = result["iso3"].isin(HIGH_TOURISM_ISO3)

    # Footnote: largest COICOP 1999-vs-2018 gap for this country and measure,
    # where it reaches 4+ points (empty otherwise).
    gaps = []
    notes = []
    for iso3, code in zip(result["iso3"], result["coicop"]):
        gap = LARGE_VERSION_GAPS.get((iso3, code))
        gaps.append(gap)
        if gap is None:
            notes.append(None)
        else:
            notes.append(
                f"Older (COICOP 1999) and current (COICOP 2018) figures for this "
                f"country differ by up to {gap:.1f} points (gap measured up to 2022)."
            )
    result["large_version_gap_pts"] = gaps
    result["version_gap_note"] = notes

    return result[COLUMN_ORDER]
