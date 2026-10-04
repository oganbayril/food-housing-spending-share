# Data notes

Data-quality issues found along the way: what was found, what (if anything)
was done about it, and why. Raw material for the README limitations section.

Every number below can be reproduced with the scripts named in each section
(outputs in `data/processed/checks/`).

## Open issues (decision needed)

### 1. Imputed rent is not estimated consistently across countries
*Script: `src/investigate_imputed_rent.py` (COICOP 2018 data, 2022)*

Housing & utilities (CP04) includes imputed rent (CP042): the rent
owner-occupiers would pay for their own home. No cash changes hands, but
national accounts count it so that owner-heavy and tenant-heavy countries are
comparable. This is why CP04 is labelled "housing & utilities", never "rent".

The problem is that countries value it very differently:
- Imputed rent is 22% of CP04 in Poland but 72% in Hungary, and its share
  barely relates to how many people own their home (correlation 0.13).
- Implied imputed rent per owner vs. actual rent per tenant ranges from
  0.29 (Malta) and 0.41 (Poland) to 4.59 (Slovenia), median 1.24. Some spread
  is expected (owners' homes are often larger, and "tenants" includes people
  paying reduced or no rent), but this range points to different estimation
  methods rather than different housing costs.
- Removing imputed rent reshuffles the housing ranking: Poland 20th -> 3rd,
  Germany 10th -> 2nd, Hungary 18th -> 29th (among the ~30 European
  countries with data).
- CH and TR do not publish imputed rent (confidential), so a version without
  it cannot be computed for them.

### 2. Totals include tourists' spending (domestic concept)
*Script: `src/investigate_tourism.py` (OECD table 5 "on the territory and abroad", 2022)*

The total used as denominator counts all household spending on a country's
territory, including by foreign visitors, and excludes residents' spending
abroad. Tourist spending inflates the total, which pushes food and housing
shares down.

For most countries the effect is within 5%. Where it is bigger, a 25% housing
share would be, on a residents-only total:
Croatia 32.4%, Greece 27.7%, Portugal 27.6%, Luxembourg 27.3%,
Iceland 26.5%, Spain 26.4%.

This is an upper bound for food, because tourists do buy some food. Malta and
Cyprus (likely affected) are not in the OECD table. 2022 only.

### 3. Provisional values
Recent years are flagged `p` (provisional) and may be revised. Values are
kept as published, with the flag carried into the processed file.

### 4. Two COICOP versions, at both Eurostat and the OECD
*Script: `src/investigate_coicop_versions.py`*

Eurostat publishes consumption by purpose in two datasets:
- `nama_10_co3_p3`: COICOP 1999. Most EU countries **stop at 2022**.
- `nama_10_cp18`: COICOP 2018. Runs to 2024/2025, includes the latest
  benchmark revisions.

The OECD has the same split (`DSD_NAMAIN10@DF_TABLE5_T501` = 1999,
`DSD_NAMAIN10@DF_TABLE5A_T501` = 2018). In 2022 the USA is only in the 1999
table and Japan only in the 2018 one.

Only in the 1999 version (Eurostat): AL, IS, MK, NO, UK (ends 2019),
XK (ends 2017). Lithuania is in 2018 only for 2020-2024.

Gap between versions where both have data (905 country-years, EU aggregates
excluded), in percentage points:

| | median | 90th percentile | max |
|---|---|---|---|
| Food | 0.08 | 1.15 | 20.06 (RO) |
| Housing & utilities | 0.18 | 1.78 | 13.76 (RO) |

Countries with the largest housing gaps: RO 13.8, CZ 6.9, LV 6.2, MT 3.3,
EE 3.2. For CZ and LV the totals themselves differ by 3-7%, so these are
revisions to the national accounts, not just the reclassification.

### 5. Romania's COICOP 2018 back-data is frozen
In `nama_10_cp18`, Romania's food and housing shares are identical every
year from 1995 to 2009 (25.68% and 26.16%). The back-years were apparently
estimated by holding the spending structure fixed. On a map with a year
slider this would show 15 years of no change, which is not real. The 1999
version has moving values for the same years.

### 6. Series breaks
COICOP 2018 data flags breaks in series (`b`) for Austria 2022 and
Belgium 2009. Values before and after a break may not be fully comparable.

## Resolved / decisions

### Country codes converted to ISO-3
Eurostat uses its own codes: Greece is `EL` (ISO `GR`), the UK is `UK`
(ISO `GB`). The OECD and Plotly use ISO-3 (`GRC`, `GBR`). A hand-written
lookup in `src/country_codes.py` converts them; a library such as pycountry
does not know `EL`/`UK`. Kosovo (`XK`) has no official ISO code; it is mapped
to `XKX` (used by the EU and World Bank). Whether Plotly can draw it is still
to be checked. EU and euro-area aggregates (`EU27_2020`, `EA20`, ...) are
excluded because they are not countries.

### Shares are computed from current-price national-currency values
`share = category (CP_MNAC) / TOTAL (CP_MNAC) * 100`. Eurostat also publishes
the share directly (`PC_TOT`), but the OECD data has no equivalent, so
computing it ourselves keeps one method for all countries. `PC_TOT` is kept as
a cross-check: all 10 test values (2022) match it within rounding (max
difference 0.04 points; Eurostat rounds to one decimal).

### Missing values are kept visible, not dropped
The loader builds the full country x category grid first, so a missing value
shows up as an empty row with no share instead of disappearing. None were
missing in the 2022 test.
