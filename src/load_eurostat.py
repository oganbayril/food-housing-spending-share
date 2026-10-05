"""Load Eurostat household consumption by purpose and compute spending shares.

Sources (both "Household final consumption expenditure by purpose"):
- nama_10_cp18:   COICOP 2018 classification (preferred, runs to 2024/2025)
- nama_10_co3_p3: COICOP 1999 classification (fallback)

Steps:
1. Download both versions and save them untouched to data/raw/.
2. Pick one version per country (see decisions.py) and keep only that one.
3. Compute food (CP01) and housing & utilities (CP04) as a % of total
   household consumption, plus imputed rent (CP042) as a % of total
   (calculation in shares.py, shared with the OECD loader).
4. Save to data/processed/eurostat_shares.csv.

Run from the project root:
    uv run python src/load_eurostat.py
"""

import pandas as pd

from country_codes import EUROSTAT_AGGREGATES, EUROSTAT_TO_ISO3
from decisions import CATEGORY_LABELS, VERSION_OVERRIDES
from shares import IMPUTED_RENT_CODE, TOTAL_CODE, UNIT_CHECK, UNIT_VALUES, compute_shares
from sources import PROCESSED_DIR, download_eurostat

# Dataset code and the name of its COICOP column, per version.
VERSIONS = {
    "2018": {"dataset": "nama_10_cp18", "coicop_column": "coicop18"},
    "1999": {"dataset": "nama_10_co3_p3", "coicop_column": "coicop"},
}


def download_version(version):
    """Download one COICOP version for all countries and years.

    Units: CP_MNAC (current prices, million national currency) to compute
    shares from, and PC_TOT (Eurostat's published share) as a cross-check.
    Current prices because a share of spending should reflect what households
    actually paid that year; national currency because a ratio within one
    country does not depend on the currency.
    """
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
    result = compute_shares(data, "Eurostat", EUROSTAT_TO_ISO3)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / "eurostat_shares.csv"
    result.to_csv(path, index=False)
    print(f"\nSaved {len(result)} rows to {path}")

    report(result, choice)


if __name__ == "__main__":
    main()
