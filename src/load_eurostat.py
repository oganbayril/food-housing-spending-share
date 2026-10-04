"""Load Eurostat household consumption by purpose and compute spending shares.

Source: Eurostat dataset nama_10_co3_p3, "Household final consumption
expenditure by purpose (COICOP 1999)".

Steps:
1. Download the data as CSV and save it untouched to data/raw/.
2. Compute food (CP01) and housing & utilities (CP04) as a % of total
   household consumption, and save the result to data/processed/.

Run from the project root:
    uv run python src/load_eurostat.py
"""

from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

DATASET = "nama_10_co3_p3"

# Small test selection first. Greece is included on purpose: Eurostat codes it
# "EL", not the ISO code "GR", and we want that mismatch visible early.
COUNTRIES = ["DE", "FR", "IT", "PL", "EL"]
YEAR = 2022

# COICOP 1999 codes. TOTAL is the denominator for the shares.
CATEGORIES = {
    "CP01": "Food and non-alcoholic beverages",
    "CP04": "Housing & utilities",
}
TOTAL_CODE = "TOTAL"

# CP_MNAC = current prices, million units of national currency.
#   We compute shares from this. Current prices (not volumes) because a share
#   of spending should reflect what households actually paid that year.
#   National currency (not euro) because a ratio within one country does not
#   depend on the currency, and it avoids exchange-rate conversion entirely.
# PC_TOT = Eurostat's own published "percentage of total".
#   Kept only as a cross-check of our calculation. We do not use it as the
#   main value because the OECD data for non-EU countries has no such column,
#   so computing the share ourselves keeps one method for every country.
UNIT_VALUES = "CP_MNAC"
UNIT_CHECK = "PC_TOT"


def build_url():
    """Build the Eurostat SDMX query URL.

    The key has one part per dimension, in the dataset's order:
    freq.unit.coicop.geo, with "+" between multiple values.
    """
    units = "+".join([UNIT_VALUES, UNIT_CHECK])
    coicop = "+".join([TOTAL_CODE] + list(CATEGORIES.keys()))
    geo = "+".join(COUNTRIES)
    key = f"A.{units}.{coicop}.{geo}"
    return (
        "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/"
        f"{DATASET}/{key}/"
        f"?format=SDMX-CSV&startPeriod={YEAR}&endPeriod={YEAR}"
    )


def download_raw():
    """Download the data and save the response exactly as received."""
    url = build_url()
    print(f"Downloading {url}")
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{DATASET}_{YEAR}.csv"
    raw_path.write_text(response.text, encoding="utf-8")
    print(f"Saved raw data to {raw_path}")
    return raw_path


def compute_shares(raw_path):
    """Turn the raw CSV into one row per country and category, with shares."""
    raw = pd.read_csv(raw_path)

    # Keep only the columns we need and give them clearer names.
    df = raw[["geo", "TIME_PERIOD", "unit", "coicop", "OBS_VALUE", "OBS_FLAG"]]
    df = df.rename(
        columns={
            "geo": "country_code",
            "TIME_PERIOD": "year",
            "OBS_VALUE": "value",
            "OBS_FLAG": "flag",
        }
    )

    values = df[df["unit"] == UNIT_VALUES]
    published = df[df["unit"] == UNIT_CHECK]

    # Total consumption per country and year: the denominator.
    totals = values[values["coicop"] == TOTAL_CODE]
    totals = totals[["country_code", "year", "value"]]
    totals = totals.rename(columns={"value": "total_mnac"})

    # Spending on each category of interest.
    spending = values[values["coicop"].isin(CATEGORIES.keys())]
    spending = spending.rename(columns={"value": "spending_mnac"})
    spending = spending.drop(columns="unit")

    # Eurostat's published percentage, for the cross-check.
    published = published[published["coicop"].isin(CATEGORIES.keys())]
    published = published[["country_code", "year", "coicop", "value"]]
    published = published.rename(columns={"value": "eurostat_pc_tot"})

    # Start from every country x category we asked for, so that anything
    # missing from the download shows up as an empty (NaN) row instead of
    # silently disappearing.
    expected_rows = []
    for country in COUNTRIES:
        for code in CATEGORIES:
            expected_rows.append(
                {"country_code": country, "year": YEAR, "coicop": code}
            )
    result = pd.DataFrame(expected_rows)

    result = result.merge(spending, on=["country_code", "year", "coicop"], how="left")
    result = result.merge(totals, on=["country_code", "year"], how="left")
    result = result.merge(published, on=["country_code", "year", "coicop"], how="left")

    result["category"] = result["coicop"].map(CATEGORIES)
    result["share_pct"] = result["spending_mnac"] / result["total_mnac"] * 100

    # How far our share is from Eurostat's published one. Eurostat rounds to
    # one decimal, so differences up to 0.05 points are just rounding.
    result["diff_vs_eurostat"] = result["share_pct"] - result["eurostat_pc_tot"]

    column_order = [
        "country_code",
        "year",
        "coicop",
        "category",
        "spending_mnac",
        "total_mnac",
        "share_pct",
        "eurostat_pc_tot",
        "diff_vs_eurostat",
        "flag",
    ]
    return result[column_order]


def report_issues(result):
    """Print data-quality issues. This only reports; it changes nothing."""
    print("\nData-quality checks:")

    missing = result[result["share_pct"].isna()]
    if len(missing) > 0:
        print(f"- {len(missing)} row(s) with no share (missing input):")
        print(missing[["country_code", "coicop"]].to_string(index=False))
    else:
        print("- No missing values.")

    flagged = result[result["flag"].notna()]
    if len(flagged) > 0:
        countries = sorted(flagged["country_code"].unique())
        flags = sorted(flagged["flag"].unique())
        print(f"- Flags {flags} on: {', '.join(countries)}")
        print("  (Eurostat flags: p = provisional, e = estimated, b = break in series)")
    else:
        print("- No flagged values.")

    # Anything beyond rounding means our method and Eurostat's disagree.
    large_diffs = result[result["diff_vs_eurostat"].abs() > 0.05]
    if len(large_diffs) > 0:
        print("- Shares differing from Eurostat's PC_TOT by more than rounding:")
        print(large_diffs.to_string(index=False))
    else:
        print("- All shares match Eurostat's published PC_TOT within rounding.")


def main():
    raw_path = download_raw()
    result = compute_shares(raw_path)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = PROCESSED_DIR / f"eurostat_shares_{YEAR}.csv"
    result.to_csv(processed_path, index=False)
    print(f"Saved processed data to {processed_path}\n")

    print(result.round(2).to_string(index=False))
    report_issues(result)


if __name__ == "__main__":
    main()
