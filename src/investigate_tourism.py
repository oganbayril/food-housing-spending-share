"""Measure how much tourist spending affects the total used as denominator.

Eurostat's consumption-by-purpose totals use the "domestic concept": all
household spending on the country's territory, including spending by foreign
visitors, and excluding residents' spending abroad. The "national concept"
covers residents only, wherever they spend.

The OECD publishes the bridge between the two (table 5 "on the territory and
abroad"):
    national (P31NC) = domestic (P31DC) - non-residents here (P34) + residents abroad (P33)

If tourists spend almost nothing on housing, switching to the national total
would multiply the housing share by P31DC / P31NC. For food the real effect
is smaller, because tourists do buy some food.

Run from the project root:
    uv run python src/investigate_tourism.py
"""

import pandas as pd

from sources import download_oecd, save_check

YEAR = 2022

# The same table exists in two COICOP versions with different country
# coverage. The totals used here do not depend on the classification, so both
# are downloaded and combined.
DATAFLOWS = {
    "2018": "OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE5A_T502,",
    "1999": "OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE5_T502,",
}


def main():
    frames = []
    for version, dataflow in DATAFLOWS.items():
        raw = download_oecd(
            dataflow,
            "A...........",
            f"oecd_t502_coicop{version}_{YEAR}.csv",
            start_year=YEAR,
            end_year=YEAR,
        )
        raw = raw[raw["PRICE_BASE"] == "V"]  # current prices
        frames.append(raw)

    # Prefer the COICOP 2018 table when a country is in both (listed first).
    combined = pd.concat(frames)
    combined = combined.drop_duplicates(subset=["REF_AREA", "TRANSACTION"], keep="first")

    wide = combined.pivot(index="REF_AREA", columns="TRANSACTION", values="OBS_VALUE")
    wide = wide.dropna(subset=["P31DC", "P31NC", "P33", "P34"])

    table = pd.DataFrame(index=wide.index)
    table["nonresident_spending_pct"] = wide["P34"] / wide["P31DC"] * 100
    table["resident_spending_abroad_pct"] = wide["P33"] / wide["P31DC"] * 100
    table["share_multiplier"] = wide["P31DC"] / wide["P31NC"]
    table["housing_25pct_would_be"] = 25 * table["share_multiplier"]
    table = table.sort_values("share_multiplier", ascending=False)
    table = table.reset_index().rename(columns={"REF_AREA": "iso3"})

    print(f"\nEffect of the domestic concept on shares, {YEAR}:")
    print(table.round(2).to_string(index=False))

    large = table[(table["share_multiplier"] - 1).abs() > 0.05]
    print(f"\nCountries where shares would change by more than 5%: {large['iso3'].tolist()}")

    save_check(table, f"tourism_effect_{YEAR}.csv")


if __name__ == "__main__":
    main()
