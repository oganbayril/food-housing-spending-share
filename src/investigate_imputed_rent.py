"""Check whether imputed rent is estimated consistently across countries.

Imputed rent (COICOP CP042) is the rent owner-occupiers "pay themselves" for
living in their own home. It is part of housing & utilities (CP04).

The check: if every country valued owner-occupied homes the same way, the
implied imputed rent per owner should be in a similar range to the actual
rent per tenant. We compare the two using Eurostat's population shares of
owners and tenants (ilc_lvho02). The population size cancels out:

    ratio = (imputed rent / owner share) / (actual rent / tenant share)

This is a rough check: owners' homes are often larger, and "tenants" includes
people paying reduced or no rent, so a ratio above 1 is expected. What matters
is how far countries spread out.

Also shows how the housing share ranking would change without imputed rent.

Run from the project root:
    uv run python src/investigate_imputed_rent.py
"""

import pandas as pd

from country_codes import EUROSTAT_AGGREGATES
from sources import download_eurostat, save_check

YEAR = 2022  # latest year with both consumption and tenure data for most countries


def main():
    spending = download_eurostat(
        "nama_10_cp18",
        "A.CP_MNAC.TOTAL+CP04+CP041+CP042.",
        f"nama_10_cp18_rent_{YEAR}.csv",
        start_year=YEAR,
        end_year=YEAR,
    )
    tenure = download_eurostat(
        "ilc_lvho02",
        "A.TOTAL.TOTAL.OWN+RENT.PC.",
        f"ilc_lvho02_{YEAR}.csv",
        start_year=YEAR,
        end_year=YEAR,
    )

    spending = spending[~spending["geo"].isin(EUROSTAT_AGGREGATES)]
    spending = spending.pivot(index="geo", columns="coicop18", values="OBS_VALUE")
    tenure = tenure.pivot(index="geo", columns="tenure", values="OBS_VALUE")

    table = pd.DataFrame(index=spending.index)
    table["imputed_pct_of_housing"] = spending["CP042"] / spending["CP04"] * 100
    table["housing_share"] = spending["CP04"] / spending["TOTAL"] * 100
    # Housing without imputed rent, as a share of spending without imputed rent
    # (imputed rent is removed from both sides so the share stays consistent).
    table["housing_share_excl_imputed"] = (
        (spending["CP04"] - spending["CP042"])
        / (spending["TOTAL"] - spending["CP042"])
        * 100
    )
    table = table.join(tenure[["OWN", "RENT"]], how="left")
    table = table.rename(columns={"OWN": "owner_pct", "RENT": "tenant_pct"})

    imputed_per_owner = spending["CP042"] / table["owner_pct"]
    rent_per_tenant = spending["CP041"] / table["tenant_pct"]
    table["owner_vs_tenant_rent_ratio"] = imputed_per_owner / rent_per_tenant

    table["rank_with_imputed"] = table["housing_share"].rank(ascending=False)
    table["rank_without_imputed"] = table["housing_share_excl_imputed"].rank(
        ascending=False
    )
    table = table.sort_values("owner_vs_tenant_rent_ratio")
    table = table.reset_index()

    print(f"\nImputed rent check, {YEAR}:")
    print(table.round(2).to_string(index=False))

    correlation = table["imputed_pct_of_housing"].corr(table["owner_pct"])
    print(f"\nCorrelation of imputed-rent share with ownership rate: {correlation:.2f}")
    ratio = table["owner_vs_tenant_rent_ratio"]
    print(
        f"Owner-vs-tenant rent ratio: median {ratio.median():.2f}, "
        f"range {ratio.min():.2f} to {ratio.max():.2f}"
    )

    missing = table[table["imputed_pct_of_housing"].isna()]["geo"].tolist()
    print(f"No imputed rent figure (missing or confidential): {missing}")

    save_check(table, f"imputed_rent_{YEAR}.csv")


if __name__ == "__main__":
    main()
