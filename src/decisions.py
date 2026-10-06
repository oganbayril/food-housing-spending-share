"""Data decisions, kept in one place so every script applies them the same way.

Each decision is explained in DATA_NOTES.md.
"""

# Which COICOP version to use per country.
# Default rule: COICOP 2018 if the country is in the 2018 data, otherwise
# COICOP 1999. One version per country for its whole series: versions are
# never mixed within a country, because a jump between versions would look
# like a real change on the map.
# Exceptions to the default rule:
VERSION_OVERRIDES = {
    # The 2018 version only covers 2020-2024 for Lithuania; the 1999 version
    # covers 1995-2023. A 29-year series beats a 5-year one.
    "LT": "1999",
}

# Which source to use per country (ISO-3).
# Default rule: Eurostat if the country is in it, otherwise the OECD. One
# source per country for its whole series: sources are never mixed.
# Exceptions to the default rule:
SOURCE_OVERRIDES = {
    # Eurostat's UK series ends in 2019; the OECD's runs to 2025. The two
    # differ by 0.5-0.9 points (cause not verified), so instead of adding the
    # OECD years to the Eurostat series, the WHOLE UK series comes from the
    # OECD. The UK is the only European country sourced from the OECD.
    "GBR": "OECD",
}

# Country-measures where the COICOP 1999 and 2018 versions differ by 4+
# points in at least one year (src/investigate_coicop_versions.py). Value:
# the largest gap in points, shown as a hover footnote for every year of that
# country and measure. Every year, not only the measured ones: the gap can
# only be measured up to 2022 (where the 1999 data ends), and for LV, RO and
# CZ it is still large in 2022, so there is no reason to think it closed.
LARGE_VERSION_GAPS = {
    ("LVA", "CP04"): 6.24,
    ("ROU", "CP04"): 7.57,  # excluding Romania's frozen 1995-2009 years
    ("CZE", "CP04"): 6.86,
    ("MNE", "CP01"): 6.29,
    ("BIH", "CP01"): 4.22,
}

# Years whose values are published but treated as missing.
# Romania's COICOP 2018 shares are identical every year from 1995 to 2009,
# so those years were estimated by holding the spending structure fixed, not
# measured.
FROZEN_BACK_DATA = {
    "RO": (1995, 2009),  # first and last year, inclusive
}

# Countries where tourist spending lowers the shares by more than 5%
# (src/investigate_tourism.py, 2022). Shares are NOT adjusted; this only
# drives a note in the hover.
HIGH_TOURISM_ISO3 = {"HRV", "GRC", "PRT", "LUX", "ISL", "ESP"}

# Time range.
# Data starts in 1995: from then on (almost) every country reports. Earlier
# years exist for a few countries only; they stay in the files, but missing
# years before 1995 are not counted as gaps.
FIRST_YEAR = 1995
# The map's year slider ends at 2024 and opens on it. 2025 is left out
# because only 16 of 38 European countries had published it (2026-10), so
# the map would look half empty and the countries present would not be a
# random sample. 2025 data stays in the processed files.
MAP_LAST_YEAR = 2024
MAP_DEFAULT_YEAR = 2024

# Tier thresholds for essentials_share (food + housing & utilities as a % of
# total spending). Rationale in DATA_NOTES.md (D14); kept unchanged after the
# checks (D15, D16). A share at or above a threshold moves up a tier.
TIER_THRESHOLDS = [35, 45]
TIER_LABELS = ["Lower", "Moderate", "Higher"]

# Countries within this many points of a threshold get a "near a tier
# boundary" hover flag (near_tier_boundary column). POST-HOC: chosen after
# seeing the D15 results, because the pre-registered margin (2.98 points)
# flagged about half of the country-years it was applied to. See D16.
NEAR_BOUNDARY_MARGIN = 1.0

# Category labels. Housing says "incl. imputed rent" because about half of it,
# in most countries, is rent that owner-occupiers do not actually pay.
CATEGORY_LABELS = {
    "CP01": "Food & non-alcoholic beverages",
    "CP04": "Housing & utilities (incl. imputed rent)",
}


def is_frozen(country_code, year):
    """True if this country-year is in a frozen back-data period."""
    if country_code not in FROZEN_BACK_DATA:
        return False
    first, last = FROZEN_BACK_DATA[country_code]
    return first <= year <= last
