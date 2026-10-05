"""Load OECD household consumption by purpose for OECD members not in Eurostat.

Sources (OECD Data Explorer, "Annual household final consumption expenditure
by purpose"):
- DSD_NAMAIN10@DF_TABLE5A_T501: COICOP 2018 (preferred)
- DSD_NAMAIN10@DF_TABLE5_T501:  COICOP 1999 (fallback)

Same rules as the Eurostat loader: one COICOP version per country, COICOP 2018
if available, and the same share calculation (shares.py).

Taken from the OECD: members NOT in the Eurostat data, plus countries that
decisions.SOURCE_OVERRIDES assigns to the OECD (the UK). Every country has
exactly one source for its whole series (see src/compare_eurostat_oecd.py for
how the two sources compare).

Run from the project root, after src/load_eurostat.py:
    uv run python src/load_oecd.py
"""

import pandas as pd

from country_codes import OECD_MEMBERS_ISO3
from decisions import SOURCE_OVERRIDES
from shares import IMPUTED_RENT_CODE, TOTAL_CODE, UNIT_VALUES, compute_shares
from sources import PROCESSED_DIR, download_oecd

DATAFLOWS = {
    "2018": "OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE5A_T501,",
    "1999": "OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE5_T501,",
}

# Key, one slot per dimension (12 in total):
# FREQ.REF_AREA.SECTOR.COUNTERPART_SECTOR.TRANSACTION.INSTR_ASSET.ACTIVITY.
# EXPENDITURE.UNIT_MEASURE.PRICE_BASE.TRANSFORMATION.TABLE_IDENTIFIER
# We fix: annual, the four expenditure items, current prices (V). The
# transaction is always P31DC (domestic concept), the same as Eurostat's.
OECD_KEY = "A.......CP01+CP04+CP042+_T..V.."

# OECD observation status -> Eurostat-style flag, so one flag column works
# for both sources. "A" (normal value) means no flag.
STATUS_TO_FLAG = {"A": None, "P": "p", "E": "e", "B": "b"}


def download_version(version):
    """Download one OECD COICOP version (all countries) in the long format."""
    raw = download_oecd(DATAFLOWS[version], OECD_KEY, f"oecd_t501_coicop{version}.csv")

    # Values are in millions (UNIT_MULT = 6) of national currency, the same
    # unit as Eurostat's CP_MNAC. Stop if that ever changes.
    if not (raw["UNIT_MULT"] == 6).all() or not (raw["UNIT_MEASURE"] == "XDC").all():
        raise ValueError("Unexpected OECD unit: expected millions of national currency")

    # Concept: P31DC = spending of residents and non-residents on the
    # territory (domestic concept), the same as Eurostat's totals. The
    # national concept would be P31NC. Stop if anything else shows up, so
    # the two sources can never be mixed on different concepts.
    transactions = set(raw["TRANSACTION"].dropna())
    if transactions != {"P31DC"}:
        raise ValueError(f"Unexpected OECD transaction(s): {transactions}")

    # Some series are listed with no observations at all (e.g. Japan in the
    # 1999 table): one row with an empty year. They carry no data, so drop
    # them, but say how many.
    no_year = raw["TIME_PERIOD"].isna()
    if no_year.sum() > 0:
        empty = sorted(raw.loc[no_year, "REF_AREA"].unique())
        print(f"  Dropped {no_year.sum()} empty placeholder rows (no year): {', '.join(empty)}")
    raw = raw[~no_year]

    data = pd.DataFrame()
    data["country_code"] = raw["REF_AREA"]
    data["year"] = raw["TIME_PERIOD"].astype(int)
    data["unit"] = UNIT_VALUES
    data["coicop"] = raw["EXPENDITURE"].replace({"_T": TOTAL_CODE})
    data["value"] = raw["OBS_VALUE"]
    data["flag"] = raw["OBS_STATUS"].map(STATUS_TO_FLAG)
    data["coicop_version"] = version

    unknown = set(raw["OBS_STATUS"].dropna()) - set(STATUS_TO_FLAG)
    if unknown:
        print(f"  Note: unmapped OECD status codes {unknown} (left without a flag)")
    return data


def choose_versions(data_2018, data_1999, countries):
    """Return {iso3: version}: COICOP 2018 if the country has totals in it."""
    has_2018 = set(data_2018.loc[data_2018["coicop"] == TOTAL_CODE, "country_code"])
    has_1999 = set(data_1999.loc[data_1999["coicop"] == TOTAL_CODE, "country_code"])

    choice = {}
    for country in sorted(countries):
        if country in has_2018:
            choice[country] = "2018"
        elif country in has_1999:
            choice[country] = "1999"
        else:
            print(f"  {country}: no OECD data in either version")
    return choice


def main():
    eurostat = pd.read_csv(PROCESSED_DIR / "eurostat_shares.csv")
    in_eurostat = set(eurostat["iso3"])

    # OECD members not covered by Eurostat, plus countries that
    # decisions.SOURCE_OVERRIDES assigns to the OECD (the UK).
    countries = []
    for iso3 in sorted(OECD_MEMBERS_ISO3):
        if iso3 not in in_eurostat or SOURCE_OVERRIDES.get(iso3) == "OECD":
            countries.append(iso3)
    print(f"Countries taken from the OECD: {', '.join(countries)}")

    data_2018 = download_version("2018")
    data_1999 = download_version("1999")
    choice = choose_versions(data_2018, data_1999, countries)

    frames = []
    for country, version in choice.items():
        if version == "2018":
            source = data_2018
        else:
            source = data_1999
        frames.append(source[source["country_code"] == country])
    data = pd.concat(frames, ignore_index=True)

    # OECD codes are already ISO-3.
    iso3_lookup = {}
    for country in choice:
        iso3_lookup[country] = country
    result = compute_shares(data, "OECD", iso3_lookup)

    path = PROCESSED_DIR / "oecd_shares.csv"
    result.to_csv(path, index=False)
    print(f"\nSaved {len(result)} rows to {path}")

    print("\nCOICOP version per country:")
    for version in ["2018", "1999"]:
        chosen = []
        for country, v in choice.items():
            if v == version:
                chosen.append(country)
        print(f"  {version}: {', '.join(chosen)}")

    no_imputed = result[(result["coicop"] == "CP04") & result["share_pct"].notna()]
    no_imputed = no_imputed[no_imputed["imputed_rent_share_pct"].isna()]
    print("\nHousing shares without an imputed-rent figure (country: years):")
    print(no_imputed.groupby("country_code").size().to_string())

    print("\nFlags:")
    print(result["flag"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
