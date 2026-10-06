"""Find countries whose food or housing share is far from the income trend.

For each year, fit a straight line across countries:
    share = a + b * log(GDP per capita, PPP)
and take each country's residual = actual share - share predicted for its
income level. A large positive residual means "spends a bigger share on this
than countries of similar income"; negative means smaller.

Why log GDP: the effect of income on spending shares works in proportions
(going from $20k to $40k matters about as much as $40k to $80k), which a
straight line in log income captures.

Why check several years: a README should not highlight a one-year blip, so
residuals are also averaged over 2015-2024 and we count in how many of those
years a country is among the five largest deviations.

Output: candidates for README outliers, with the data caveats that apply to
each (so a caveat-driven outlier is not presented as a real difference).

Run from the project root, after src/analyze_essentials.py:
    uv run python src/find_outliers.py
"""

import numpy as np
import pandas as pd

from decisions import MAP_DEFAULT_YEAR
from sources import CHECKS_DIR, PROCESSED_DIR, download_worldbank, save_check

RECENT_FROM = 2015
TOP_N = 5


def residuals_for_year(group, column):
    """Fit share on log GDP for one year; return residuals and R-squared."""
    x = np.log(group["gdp_pc"])
    y = group[column]
    slope, intercept = np.polyfit(x, y, 1)
    predicted = intercept + slope * x
    residual = y - predicted
    r_squared = 1 - (residual ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return residual, r_squared


def caveats_by_country():
    """Data caveats per country (from the processed file), as short text."""
    shares = pd.read_csv(PROCESSED_DIR / "shares.csv")
    latest = shares[shares["year"] == MAP_DEFAULT_YEAR]
    notes = {}
    for iso3, group in latest.groupby("iso3"):
        items = []
        if group["source"].iloc[0] == "OECD" and iso3 == "GBR":
            items.append("UK from OECD (+0.5-0.9 pt source gap)")
        if group["high_tourism"].iloc[0]:
            items.append("tourism lowers shares")
        for code, note in zip(group["coicop"], group["large_version_gap_pts"]):
            if pd.notna(note):
                items.append(f"{code} version gap up to {note:.1f} pts")
        housing = group[group["coicop"] == "CP04"]
        if housing["share_pct"].notna().any() and housing["imputed_rent_share_pct"].isna().all():
            items.append("no imputed-rent figure")
        notes[iso3] = "; ".join(items)
    return notes


def main():
    table = pd.read_csv(CHECKS_DIR / "essentials_by_country_year.csv")
    gdp = download_worldbank("NY.GDP.PCAP.PP.CD", "worldbank_gdp_pc_ppp.json", RECENT_FROM, MAP_DEFAULT_YEAR)
    gdp = gdp.rename(columns={"value": "gdp_pc"}).dropna(subset=["gdp_pc"])
    table = table.merge(gdp, on=["iso3", "year"])
    table = table[table["year"] >= RECENT_FROM]

    frames = []
    fit_quality = []
    for year, group in table.groupby("year"):
        group = group.copy()
        for measure in ["food", "housing"]:
            residual, r_squared = residuals_for_year(group, f"{measure}_share")
            group[f"{measure}_residual"] = residual
            fit_quality.append({"year": year, "measure": measure, "r_squared": r_squared, "n": len(group)})
        frames.append(group)
    table = pd.concat(frames)
    save_check(table, "income_residuals.csv")

    fit_quality = pd.DataFrame(fit_quality)
    print(f"Fit of share ~ log(GDP per capita), R-squared ({RECENT_FROM}-{MAP_DEFAULT_YEAR}):")
    print(fit_quality.groupby("measure")["r_squared"].agg(["min", "median", "max"]).round(2).to_string())

    caveats = caveats_by_country()

    for measure in ["food", "housing"]:
        column = f"{measure}_residual"

        # How often each country is among the TOP_N largest |residuals|.
        in_top = {}
        for year, group in table.groupby("year"):
            top = group.reindex(group[column].abs().sort_values(ascending=False).index).head(TOP_N)
            for iso3 in top["iso3"]:
                in_top[iso3] = in_top.get(iso3, 0) + 1

        latest = table[table["year"] == MAP_DEFAULT_YEAR][["iso3", f"{measure}_share", column]]
        average = table.groupby("iso3")[column].mean().rename(f"mean_residual_{RECENT_FROM}_{MAP_DEFAULT_YEAR}")
        summary = latest.merge(average, on="iso3")
        summary["years_in_top5"] = summary["iso3"].map(in_top).fillna(0).astype(int)
        summary["caveats"] = summary["iso3"].map(caveats).fillna("")
        summary = summary.reindex(summary[column].abs().sort_values(ascending=False).index)

        n_years = table["year"].nunique()
        print(f"\n{measure.upper()} share: largest deviations from the income trend in {MAP_DEFAULT_YEAR}")
        print(f"(residual in percentage points; years_in_top5 out of {n_years} years)")
        print(summary.head(8).round(1).to_string(index=False))
        save_check(summary, f"outliers_{measure}.csv")


if __name__ == "__main__":
    main()
