"""Load Eurostat household consumption by purpose and compute spending shares.

Sources (both "Household final consumption expenditure by purpose"):
- nama_10_cp18:   COICOP 2018 classification (preferred, runs to 2024/2025)
- nama_10_co3_p3: COICOP 1999 classification (fallback)

Steps:
1. Download both versions and save them untouched to data/raw/.
2. Pick one version per country (see decisions.py) and keep only that one.
3. Compute food (CP01) and housing & utilities (CP04) as a % of total
   household consumption, plus imputed rent (CP042) as a % of total.
4. Save one tidy table to data/processed/eurostat_shares.csv.

Run from the project root:
    uv run python src/load_eurostat.py
"""

import pandas as pd

from country_codes import EUROSTAT_AGGREGATES, EUROSTAT_TO_ISO3
from decisions import (
    CATEGORY_LABELS,
    HIGH_TOURISM_ISO3,
    VERSION_OVERRIDES,
    is_frozen,
)
from sources import PROCESSED_DIR, download_eurostat

# Dataset code and the name of its COICOP column, per version.
VERSIONS = {
    "2018": {"dataset": "nama_10_cp18", "coicop_column": "coicop18"},
    "1999": {"dataset": "nama_10_co3_p3", "coicop_column": "coicop"},
}

# CP_MNAC = current prices, million units of national currency. Shares are
#   computed from this. Current prices because a share of spending should
#   reflect what households actually paid that year. National currency
#   because a ratio within one country does not depend on the currency.
# PC_TOT = Eurostat's own published "percentage of total", kept only as a
#   cross-check of our calculation (the OECD data has no such column, so
#   computing the share ourselves keeps one method for every country).
UNIT_VALUES = "CP_MNAC"
UNIT_CHECK = "PC_TOT"

TOTAL_CODE = "TOTAL"
IMPUTED_RENT_CODE = "CP042"

# The map's time range starts in 1995: from then on (almost) every country
# reports. Earlier years exist for only a few countries (DK, FR, FI, NO, SE)
# and are kept in the file, but missing years before 1995 are not counted
# as gaps.
FIRST_YEAR = 1995


def download_version(version):
    """Download one COICOP version for all countries and years."""
    dataset = VERSIONS[version]["dataset"]
    coicop_column = VERSIONS[version]["coicop_column"]

    items = [TOTAL_CODE, IMPUTED_RENT_CODE] + list(CATEGORY_LABELS.keys())
    key = f"A.{UNIT_VALUES}+{UNIT_CHECK}.{'+'.join(items)}."  # empty geo = all
    raw = download_eurostat(dataset, key, f"{dataset}.csv")

    # Same column names for both versions, so they can be combined.
    raw = raw.rename(
        columns={
            coicop_column: "coicop",
            "geo": "country_code",
            "TIME_PERIOD": "year",
            "OBS_VALUE": "value",
            "OBS_FLAG": "flag",
        }
    )
    raw = raw[["country_code", "year", "unit", "coicop", "value", "flag"]]
    raw = raw[~raw["country_code"].isin(EUROSTAT_AGGREGATES)]
    raw["coicop_version"] = version
    return raw


def choose_versions(raw_2018, raw_1999):
    """Return {country_code: version}, one version per country.

    Rule: COICOP 2018 if the country has totals in it, otherwise 1999,
    unless decisions.VERSION_OVERRIDES says otherwise.
    """
    has_2018 = set(raw_2018.loc[raw_2018["coicop"] == TOTAL_CODE, "country_code"])
    has_1999 = set(raw_1999.loc[raw_1999["coicop"] == TOTAL_CODE, "country_code"])

    choice = {}
    for country in sorted(has_2018 | has_1999):
        if country in VERSION_OVERRIDES:
            choice[country] = VERSION_OVERRIDES[country]
        elif country in has_2018:
            choice[country] = "2018"
        else:
            choice[country] = "1999"
    return choice


def keep_chosen_version(raw_2018, raw_1999, choice):
    """Keep each country's rows from its chosen version only (never mixed)."""
    frames = []
    for country, version in choice.items():
        if version == "2018":
            source = raw_2018
        else:
            source = raw_1999
        frames.append(source[source["country_code"] == country])
    return pd.concat(frames, ignore_index=True)


def build_grid(data):
    """Every country x year x category we expect, so gaps stay visible.

    Years run from 1995 (or a country's first year, if earlier) to the latest
    year in the data. A country-year that Eurostat does not publish becomes a
    row with no values instead of silently not existing.
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


def compute_shares(data):
    """One row per country, year and category, with the share and context."""
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

    result["iso3"] = result["country_code"].map(EUROSTAT_TO_ISO3)
    result["category"] = result["coicop"].map(CATEGORY_LABELS)
    result["share_pct"] = result["spending_mnac"] / result["total_mnac"] * 100

    # Imputed rent as a % of total spending, shown in the housing hover
    # ("of which imputed rent: X%"). Only meaningful on the housing rows.
    imputed_share = result["imputed_rent_mnac"] / result["total_mnac"] * 100
    result["imputed_rent_share_pct"] = imputed_share.where(result["coicop"] == "CP04")

    # A share is provisional/estimated if either the category or the total
    # is, so take the category's flag and fall back to the total's.
    result["flag"] = result["flag"].fillna(result["total_flag"])

    # Frozen back-data: keep the published values, but no share.
    frozen = []
    for country, year in zip(result["country_code"], result["year"]):
        frozen.append(is_frozen(country, year))
    result["frozen_back_data"] = frozen
    result.loc[result["frozen_back_data"], "share_pct"] = None
    result.loc[result["frozen_back_data"], "imputed_rent_share_pct"] = None

    result["diff_vs_eurostat"] = result["share_pct"] - result["eurostat_pc_tot"]
    result["high_tourism"] = result["iso3"].isin(HIGH_TOURISM_ISO3)

    column_order = [
        "country_code",
        "iso3",
        "year",
        "coicop_version",
        "coicop",
        "category",
        "spending_mnac",
        "total_mnac",
        "share_pct",
        "imputed_rent_share_pct",
        "eurostat_pc_tot",
        "diff_vs_eurostat",
        "flag",
        "frozen_back_data",
        "high_tourism",
    ]
    return result[column_order]


def report(result, choice):
    """Print checks. This only reports; it changes nothing."""
    print("\nCOICOP version per country:")
    for version in ["2018", "1999"]:
        countries = []
        for country, chosen in choice.items():
            if chosen == version:
                countries.append(country)
        print(f"  {version}: {', '.join(countries)}")

    unmapped = result.loc[result["iso3"].isna(), "country_code"].unique()
    print(f"\nCountry codes without an ISO-3 mapping: {list(unmapped)}")

    # Anything beyond rounding means our method and Eurostat's disagree.
    # Eurostat rounds PC_TOT to one decimal, so up to 0.05 is rounding.
    compared = result.dropna(subset=["diff_vs_eurostat"])
    large = compared[compared["diff_vs_eurostat"].abs() > 0.05]
    print(
        f"\nCross-check against Eurostat's PC_TOT: {len(compared)} shares compared, "
        f"{len(large)} differ by more than rounding"
    )
    if len(large) > 0:
        print(large[["country_code", "year", "coicop", "share_pct", "eurostat_pc_tot"]].to_string(index=False))

    print("\nFlags on computed shares:")
    print(result["flag"].value_counts(dropna=False).to_string())


def main():
    raw_2018 = download_version("2018")
    raw_1999 = download_version("1999")

    choice = choose_versions(raw_2018, raw_1999)
    data = keep_chosen_version(raw_2018, raw_1999, choice)
    result = compute_shares(data)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / "eurostat_shares.csv"
    result.to_csv(path, index=False)
    print(f"\nSaved {len(result)} rows to {path}")

    report(result, choice)


if __name__ == "__main__":
    main()
