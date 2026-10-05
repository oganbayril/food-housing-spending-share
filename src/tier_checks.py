"""Check how robust tier assignments are to the COICOP version choice.

Not run yet: the tier thresholds have not been chosen. Once they are, call
the two functions below with them, e.g.

    thresholds = [20, 25]   # boundaries between green/yellow and yellow/red
    find_tier_disagreements(overlap, "housing", thresholds)

Two kinds of check:
1. find_tier_disagreements: for country-years published in BOTH COICOP
   versions, does the 1999 value fall in a different tier than the 2018 one?
   This is a direct test with no assumptions.
2. find_near_boundary: for any country-year, is the value within `margin`
   percentage points of a boundary? Used for countries with only one version,
   where no gap can be observed, so the margin is borrowed from the countries
   that have both (see the uncertainty margin in DATA_NOTES.md).
"""

import pandas as pd


def assign_tier(share, thresholds):
    """Return the tier number for a share: 0 below the first threshold,
    1 between the first and second, and so on. NaN stays NaN."""
    if pd.isna(share):
        return None
    tier = 0
    for threshold in sorted(thresholds):
        if share >= threshold:
            tier += 1
    return tier


def find_tier_disagreements(overlap, measure, thresholds):
    """Rows where the 1999 and 2018 values land in different tiers.

    `overlap` is data/processed/checks/coicop_versions_overlap.csv, with
    columns like "housing_share_1999" and "housing_share_2018".
    `measure` is "food" or "housing".
    """
    column_1999 = f"{measure}_share_1999"
    column_2018 = f"{measure}_share_2018"

    result = overlap[["geo", "year", column_1999, column_2018]].copy()
    result["tier_1999"] = result[column_1999].apply(assign_tier, args=(thresholds,))
    result["tier_2018"] = result[column_2018].apply(assign_tier, args=(thresholds,))
    return result[result["tier_1999"] != result["tier_2018"]]


def find_near_boundary(shares, share_column, thresholds, margin):
    """Rows whose share is within `margin` points of any threshold.

    `shares` is any table with a share column, e.g. the processed shares file.
    """
    result = shares.copy()
    distances = []
    for share in result[share_column]:
        if pd.isna(share):
            distances.append(None)
            continue
        closest = None
        for threshold in thresholds:
            distance = abs(share - threshold)
            if closest is None or distance < closest:
                closest = distance
        distances.append(closest)
    result["distance_to_boundary"] = distances
    return result[result["distance_to_boundary"] <= margin]
