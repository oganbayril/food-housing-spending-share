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

# Category labels. Housing says "incl. imputed rent" because more than half of
# it, in most countries, is rent that owner-occupiers do not actually pay.
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
