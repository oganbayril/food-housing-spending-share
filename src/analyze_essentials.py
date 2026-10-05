"""Check the provisional tier thresholds against the data.

The thresholds and these checks were fixed in DATA_NOTES.md (D14) before
this script was run. It reports; it does not change any threshold.

1. Distribution of essentials_share (food + housing & utilities, % of total
   spending): 2024 and all map years, as a text histogram, with tier counts.
2. Rank (Spearman) correlation with Eurostat's housing cost overburden rate.
3. Rank correlation with GDP per capita (World Bank, PPP).
4. Boundary checks (src/tier_checks.py), both types.

Spearman correlation = the ordinary (Pearson) correlation of the RANKS. It
asks "do countries that rank high on one measure also rank high on the
other?", which is what matters for tiers, and is not thrown off by a few
extreme values.

Run from the project root, after src/combine_sources.py and
src/investigate_coicop_versions.py:
    uv run python src/analyze_essentials.py
"""

import math

import pandas as pd

from country_codes import EUROSTAT_AGGREGATES, EUROSTAT_TO_ISO3
from decisions import FIRST_YEAR, MAP_DEFAULT_YEAR, MAP_LAST_YEAR, TIER_LABELS, TIER_THRESHOLDS
from sources import CHECKS_DIR, PROCESSED_DIR, download_eurostat, download_worldbank, save_check
from tier_checks import assign_tier, find_near_boundary, find_tier_disagreements

SINGLE_TIER_LIMIT = 0.70  # D14: above this share of countries in one tier, stop and ask
BIN_WIDTH = 2.5  # histogram bin width, percentage points


def spearman(a, b):
    """Spearman rank correlation: Pearson correlation of the ranks."""
    return a.rank().corr(b.rank())


def load_country_years():
    """One row per country-year (map years only) with food, housing, essentials."""
    shares = pd.read_csv(PROCESSED_DIR / "shares.csv")
    shares = shares[(shares["year"] >= FIRST_YEAR) & (shares["year"] <= MAP_LAST_YEAR)]

    food = shares[shares["coicop"] == "CP01"]
    food = food[["iso3", "year", "source", "coicop_version", "share_pct", "essentials_share"]]
    food = food.rename(columns={"share_pct": "food_share"})

    housing = shares[shares["coicop"] == "CP04"][["iso3", "year", "share_pct"]]
    housing = housing.rename(columns={"share_pct": "housing_share"})

    table = food.merge(housing, on=["iso3", "year"])
    table = table.dropna(subset=["essentials_share"])

    tiers = []
    for share in table["essentials_share"]:
        tiers.append(TIER_LABELS[assign_tier(share, TIER_THRESHOLDS)])
    table["tier"] = tiers
    return table


def text_histogram(values, title):
    """Print a histogram with one row per bin, using # marks."""
    print(f"\n{title} (n = {len(values)}, bins of {BIN_WIDTH} points)")
    low = math.floor(values.min() / BIN_WIDTH) * BIN_WIDTH
    high = math.ceil(values.max() / BIN_WIDTH) * BIN_WIDTH
    edge = low
    while edge < high:
        count = ((values >= edge) & (values < edge + BIN_WIDTH)).sum()
        marker = ""
        for threshold in TIER_THRESHOLDS:
            if edge == threshold:
                marker = f"  <- {threshold}% threshold"
        print(f"  {edge:5.1f}-{edge + BIN_WIDTH:5.1f}% | {'#' * count} {count}{marker}")
        edge += BIN_WIDTH


def tier_counts(table, label):
    counts = table["tier"].value_counts().reindex(TIER_LABELS, fill_value=0)
    shares = counts / counts.sum()
    print(f"\nTier counts, {label}:")
    for tier in TIER_LABELS:
        print(f"  {tier:9s} {counts[tier]:5d}  ({shares[tier] * 100:.0f}%)")
    return counts, shares


def report_distribution(table):
    """Check 1: distribution and tier counts."""
    print("=" * 70)
    print("1. DISTRIBUTION OF ESSENTIALS_SHARE")
    latest = table[table["year"] == MAP_DEFAULT_YEAR]

    text_histogram(latest["essentials_share"], f"{MAP_DEFAULT_YEAR}, countries")
    counts, shares = tier_counts(latest, f"{MAP_DEFAULT_YEAR} (countries)")
    print(f"\n{MAP_DEFAULT_YEAR} by tier:")
    for tier in TIER_LABELS:
        in_tier = latest[latest["tier"] == tier].sort_values("essentials_share")
        listing = []
        for iso3, share in zip(in_tier["iso3"], in_tier["essentials_share"]):
            listing.append(f"{iso3} {share:.1f}")
        print(f"  {tier}: {', '.join(listing)}")

    text_histogram(table["essentials_share"], f"All map years {FIRST_YEAR}-{MAP_LAST_YEAR}, country-years")
    tier_counts(table, f"all map years (country-years)")

    print("\nSummary statistics:")
    summary = pd.DataFrame(
        {
            f"{MAP_DEFAULT_YEAR}": latest["essentials_share"].describe(),
            "all years": table["essentials_share"].describe(),
        }
    )
    print(summary.round(1).to_string())

    largest = shares.max()
    if largest > SINGLE_TIER_LIMIT:
        print(
            f"\n*** STOP RULE (D14): {largest * 100:.0f}% of countries are in the "
            f"'{shares.idxmax()}' tier in {MAP_DEFAULT_YEAR} (limit "
            f"{SINGLE_TIER_LIMIT * 100:.0f}%). Thresholds NOT changed; decision for the "
            f"project owner. ***"
        )
    else:
        print(f"\nStop rule (D14) not triggered: largest tier holds {largest * 100:.0f}%.")

    per_year = table.pivot_table(index="year", columns="tier", values="iso3", aggfunc="count")
    per_year = per_year.reindex(columns=TIER_LABELS).fillna(0).astype(int)
    save_check(per_year.reset_index(), "tier_counts_by_year.csv")


def correlation_report(table, other, other_name, columns):
    """Spearman correlations: pooled, in the default year, and per year."""
    merged = table.merge(other, on=["iso3", "year"]).dropna(subset=["value"])
    print(
        f"\nMatched country-years: {len(merged)} "
        f"({merged['iso3'].nunique()} countries, {merged['year'].min()}-{merged['year'].max()})"
    )
    rows = []
    for column in columns:
        pooled = spearman(merged[column], merged["value"])
        latest = merged[merged["year"] == MAP_DEFAULT_YEAR]
        in_latest = spearman(latest[column], latest["value"])

        yearly = []
        for year, group in merged.groupby("year"):
            if len(group) >= 10:  # too few countries make a yearly value meaningless
                yearly.append(spearman(group[column], group["value"]))
        yearly = pd.Series(yearly)

        rows.append(
            {
                "measure": column,
                "vs": other_name,
                "pooled_rho": round(pooled, 2),
                f"rho_{MAP_DEFAULT_YEAR}": round(in_latest, 2),
                f"n_{MAP_DEFAULT_YEAR}": len(latest),
                "yearly_rho_median": round(yearly.median(), 2),
                "yearly_rho_min": round(yearly.min(), 2),
                "yearly_rho_max": round(yearly.max(), 2),
                "n_years": len(yearly),
            }
        )
    result = pd.DataFrame(rows)
    print(result.to_string(index=False))
    return result


def report_overburden(table):
    """Check 2: rank correlation with the housing cost overburden rate."""
    print("\n" + "=" * 70)
    print("2. RANK CORRELATION WITH HOUSING COST OVERBURDEN RATE (Eurostat ilc_lvho07a)")
    # Dimensions: freq.unit.rskpovth.age.sex.geo -> total population.
    raw = download_eurostat("ilc_lvho07a", "A.PC.TOTAL.TOTAL.T.", "ilc_lvho07a.csv")
    raw = raw[~raw["geo"].isin(EUROSTAT_AGGREGATES)]
    raw = raw[raw["geo"].isin(EUROSTAT_TO_ISO3.keys())]  # drops other aggregates (EU28, EA18, ...)
    overburden = pd.DataFrame(
        {
            "iso3": raw["geo"].map(EUROSTAT_TO_ISO3),
            "year": raw["TIME_PERIOD"],
            "value": raw["OBS_VALUE"],
        }
    )
    result = correlation_report(
        table, overburden, "overburden_rate", ["essentials_share", "housing_share", "food_share"]
    )
    save_check(result, "correlation_overburden.csv")


def report_gdp(table):
    """Check 3: rank correlation with GDP per capita (PPP)."""
    print("\n" + "=" * 70)
    print("3. RANK CORRELATION WITH GDP PER CAPITA (World Bank NY.GDP.PCAP.PP.CD, PPP)")
    gdp = download_worldbank("NY.GDP.PCAP.PP.CD", "worldbank_gdp_pc_ppp.json", FIRST_YEAR, MAP_LAST_YEAR)
    missing = sorted(set(table["iso3"]) - set(gdp.dropna(subset=["value"])["iso3"]))
    print(f"Countries without World Bank GDP data: {missing if missing else 'none'}")
    result = correlation_report(
        table, gdp, "gdp_per_capita_ppp", ["essentials_share", "housing_share", "food_share"]
    )
    save_check(result, "correlation_gdp.csv")


def essentials_version_overlap():
    """Country-years in both COICOP versions, with essentials in each."""
    eurostat = pd.read_csv(CHECKS_DIR / "coicop_versions_overlap.csv")
    eurostat["iso3"] = eurostat["geo"].map(EUROSTAT_TO_ISO3)

    oecd = pd.read_csv(CHECKS_DIR / "oecd_versions_overlap.csv")  # Israel
    oecd = oecd.pivot_table(index=["iso3", "year"], columns="coicop", values=["oecd_1999", "oecd_2018"])
    oecd_rows = pd.DataFrame(
        {
            "food_share_1999": oecd[("oecd_1999", "CP01")],
            "housing_share_1999": oecd[("oecd_1999", "CP04")],
            "food_share_2018": oecd[("oecd_2018", "CP01")],
            "housing_share_2018": oecd[("oecd_2018", "CP04")],
        }
    ).reset_index()

    overlap = pd.concat([eurostat, oecd_rows], ignore_index=True)
    # Map years only: a tier change in, say, 1980 can never be seen on the map.
    overlap = overlap[(overlap["year"] >= FIRST_YEAR) & (overlap["year"] <= MAP_LAST_YEAR)]
    overlap["geo"] = overlap["iso3"]  # tier_checks reports the "geo" column
    overlap["essentials_share_1999"] = overlap["food_share_1999"] + overlap["housing_share_1999"]
    overlap["essentials_share_2018"] = overlap["food_share_2018"] + overlap["housing_share_2018"]
    overlap["essentials_gap"] = overlap["essentials_share_2018"] - overlap["essentials_share_1999"]
    return overlap


def uk_source_gap():
    """Largest Eurostat-vs-OECD difference in the UK's essentials share."""
    eurostat = pd.read_csv(PROCESSED_DIR / "eurostat_shares.csv")
    oecd = pd.read_csv(PROCESSED_DIR / "oecd_shares.csv")
    eurostat = eurostat[(eurostat["iso3"] == "GBR") & (eurostat["coicop"] == "CP01")]
    oecd = oecd[(oecd["iso3"] == "GBR") & (oecd["coicop"] == "CP01")]
    both = eurostat[["year", "essentials_share"]].merge(
        oecd[["year", "essentials_share"]], on="year", suffixes=("_eurostat", "_oecd")
    )
    both = both.dropna()
    return (both["essentials_share_oecd"] - both["essentials_share_eurostat"]).abs().max()


def report_boundaries(table):
    """Check 4: both boundary checks."""
    print("\n" + "=" * 70)
    print(f"4. BOUNDARY CHECKS (thresholds {TIER_THRESHOLDS})")
    overlap = essentials_version_overlap()

    # Type 1: does the COICOP version change the tier?
    disagreements = find_tier_disagreements(overlap, "essentials", TIER_THRESHOLDS)
    print(
        f"\nType 1: tier differs between COICOP 1999 and 2018 in "
        f"{len(disagreements)} of {len(overlap)} overlapping country-years "
        f"({overlap['year'].min()}-{overlap['year'].max()})."
    )
    if len(disagreements) > 0:
        summary = disagreements.groupby("geo")["year"].agg(["count", "min", "max"])
        print(summary.to_string())
    save_check(disagreements, "boundary_type1_version_disagreements.csv")

    # Margin for type 2 (fixed in D14): 90th percentile of the essentials
    # version gap from 2020 onwards.
    recent = overlap[overlap["year"] >= 2020]
    margin = recent["essentials_gap"].abs().quantile(0.9)
    uk_extra = uk_source_gap()
    print(
        f"\nEssentials version gap from 2020: median {recent['essentials_gap'].abs().median():.2f}, "
        f"90th percentile {margin:.2f}, max {recent['essentials_gap'].abs().max():.2f} points"
    )
    print(f"Margin: {margin:.2f} points; UK: {margin:.2f} + {uk_extra:.2f} (Eurostat vs OECD) = {margin + uk_extra:.2f}")

    # Type 2: countries whose version gap cannot be observed.
    observed = set(overlap["iso3"])
    unobserved = table[~table["iso3"].isin(observed)]
    print(f"\nType 2: countries with no observable version gap: {', '.join(sorted(unobserved['iso3'].unique()))}")

    frames = []
    for iso3, group in unobserved.groupby("iso3"):
        country_margin = margin
        if iso3 == "GBR":
            country_margin = margin + uk_extra
        frames.append(find_near_boundary(group, "essentials_share", TIER_THRESHOLDS, country_margin))
    near = pd.concat(frames)
    print(f"{len(near)} of {len(unobserved)} country-years lie within the margin of a threshold.")
    if len(near) > 0:
        summary = near.groupby("iso3")["year"].agg(["count", "min", "max"])
        print(summary.to_string())
        latest = near[near["year"] == MAP_DEFAULT_YEAR]
        listing = []
        for iso3, share in zip(latest["iso3"], latest["essentials_share"]):
            listing.append(f"{iso3} {share:.1f}")
        print(f"In {MAP_DEFAULT_YEAR}: {', '.join(listing) if listing else 'none'}")
    save_check(near, "boundary_type2_near_threshold.csv")


def main():
    table = load_country_years()
    save_check(table, "essentials_by_country_year.csv")
    report_distribution(table)
    report_overburden(table)
    report_gdp(table)
    report_boundaries(table)


if __name__ == "__main__":
    main()
