"""Country code lookups.

Eurostat uses its own two-letter codes, which are mostly ISO 3166 alpha-2 with
two exceptions: Greece is "EL" (ISO: GR) and the United Kingdom is "UK"
(ISO: GB). The OECD and Plotly's world map both use ISO 3166 alpha-3 ("DEU").
Everything is converted to ISO-3 so the two sources can be joined and mapped.

The mapping is written out by hand instead of using a library such as
pycountry, because pycountry does not know Eurostat's "EL"/"UK" codes and the
list is short enough to check by eye.
"""

EUROSTAT_TO_ISO3 = {
    # EU member states
    "AT": "AUT",
    "BE": "BEL",
    "BG": "BGR",
    "CY": "CYP",
    "CZ": "CZE",
    "DE": "DEU",
    "DK": "DNK",
    "EE": "EST",
    "EL": "GRC",  # Eurostat code differs from ISO alpha-2 "GR"
    "ES": "ESP",
    "FI": "FIN",
    "FR": "FRA",
    "HR": "HRV",
    "HU": "HUN",
    "IE": "IRL",
    "IT": "ITA",
    "LT": "LTU",
    "LU": "LUX",
    "LV": "LVA",
    "MT": "MLT",
    "NL": "NLD",
    "PL": "POL",
    "PT": "PRT",
    "RO": "ROU",
    "SE": "SWE",
    "SI": "SVN",
    "SK": "SVK",
    # EFTA, United Kingdom, candidate and potential candidate countries
    "CH": "CHE",
    "IS": "ISL",
    "NO": "NOR",
    "UK": "GBR",  # Eurostat code differs from ISO alpha-2 "GB"
    "AL": "ALB",
    "BA": "BIH",
    "ME": "MNE",
    "MK": "MKD",
    "RS": "SRB",
    "TR": "TUR",
    # Kosovo has no official ISO code. "XKX" is the user-assigned code used by
    # the EU and World Bank. Whether Plotly's map has a shape for it is still
    # to be checked at the map step.
    "XK": "XKX",
}

# The 38 OECD member countries (2026). Those not in the Eurostat data are
# loaded from the OECD instead. The OECD tables also contain some
# non-members (e.g. Brazil, Hong Kong); they are out of scope.
OECD_MEMBERS_ISO3 = {
    "AUS", "AUT", "BEL", "CAN", "CHE", "CHL", "COL", "CRI", "CZE", "DEU",
    "DNK", "ESP", "EST", "FIN", "FRA", "GBR", "GRC", "HUN", "IRL", "ISL",
    "ISR", "ITA", "JPN", "KOR", "LTU", "LUX", "LVA", "MEX", "NLD", "NOR",
    "NZL", "POL", "PRT", "SVK", "SVN", "SWE", "TUR", "USA",
}

# Eurostat also publishes regional aggregates (EU, euro area). They are not
# countries, so they are excluded from the country-level data.
EUROSTAT_AGGREGATES = {"EU27_2020", "EA", "EA12", "EA19", "EA20", "EA21"}
