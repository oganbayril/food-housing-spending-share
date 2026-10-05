# Data notes

Data-quality issues found along the way: what was found, what was decided,
and why. Raw material for the README limitations section.

Every number below can be reproduced with the script named in each section
(outputs in `data/processed/checks/`). Decisions are applied in code through
`src/decisions.py`.

## Decisions

### D1. COICOP version: prefer 2018, fall back to 1999, never mix within a country
*Script: `src/investigate_coicop_versions.py`*

Eurostat and the OECD both publish consumption by purpose in two
classifications:

| | COICOP 1999 | COICOP 2018 |
|---|---|---|
| Eurostat | `nama_10_co3_p3` (most EU countries stop at 2022) | `nama_10_cp18` (to 2024/2025, latest revisions) |
| OECD | `DSD_NAMAIN10@DF_TABLE5_T501` | `DSD_NAMAIN10@DF_TABLE5A_T501` |

Rule:
- COICOP 2018 if a country is in it, otherwise 1999.
- One version per country for its whole series. A switch between versions
  inside a series would show up on the map as a jump that is not real.
- `coicop_version` column records which one each row comes from.

Result (Eurostat): 31 countries on 2018; AL, IS, LT, MK, NO, UK, XK on 1999.

Exception: **Lithuania uses 1999** (1995-2023), because its 2018 series only
covers 2020-2024.

Why not prefer 1999 (the original plan, chosen because it matched Eurostat):
Eurostat itself has moved to 2018, and the 1999 data ends in 2022 for most
countries.

### D2. Uncertainty margin from the version choice
Gap between the two versions' shares where both exist (Eurostat, 890
country-years, Romania's frozen years excluded), in percentage points:

| Period | Food: median | Food: 90th pct | Food: max | Housing: median | Housing: 90th pct | Housing: max |
|---|---|---|---|---|---|---|
| Before 2015 | 0.03 | 1.11 | 6.29 (ME 2006) | 0.13 | 1.50 | 6.95 (RO 2013) |
| 2015 onwards | 0.21 | 1.14 | 4.37 (ME 2023) | 0.30 | 2.76 | 7.57 (RO 2016) |
| 2020 onwards | 0.24 | 1.24 | 4.37 (ME 2023) | 0.33 | 2.31 | 7.11 (RO 2020) |

The gap is larger in recent years, which is what the map will mostly show.
Typical gap (median): about 0.2-0.3 points. Worst case: about 4 points for
food, about 7 for housing. Largest housing gaps by country: RO, CZ (6.9),
LV (6.2), MT (3.3), EE (3.2). For CZ and LV the totals themselves differ by
3-7%, so this is a revision of the national accounts, not only the
reclassification.

Tier boundary check (`src/tier_checks.py`, ready to run once thresholds are
set):
1. Country-years in both versions whose 1999 and 2018 values fall in
   different tiers (direct test).
2. Country-years with only one version that lie within the margin of a tier
   boundary (margin borrowed from the table above).

### D3. Romania 1995-2009 treated as missing
In `nama_10_cp18`, Romania's food and housing shares are identical every year
from 1995 to 2009 (25.68% and 26.16%): the back-years were estimated by
holding the spending structure fixed, not measured. These 15 years keep their
published values in the processed file, but have no share
(`frozen_back_data = True`). Romania's map series starts in 2010. Filling the
gap from the 1999 version would mix versions within a country (D1).

### D4. Housing keeps imputed rent, and says so
Label: **"Housing & utilities (incl. imputed rent)"**. The imputed-rent share
of total spending is stored (`imputed_rent_share_pct`) for the hover.

Why keep it, despite issue L1 below:
- It is the standard national-accounts definition, and the only one
  available for CH and TR.
- Without it, owners' housing costs almost vanish: mortgage payments are not
  consumption at all, so only utilities and repairs would remain.

### D5. Tourism: shares not adjusted, hover note instead
Countries where tourist spending lowers shares by more than 5% (L2 below) get
a hover note (`high_tourism = True`): HR, EL, PT, LU, IS, ES. Not adjusted,
because there is no residents-only breakdown by category, and adjusting would
mix sources.

### D6. Provisional values and series breaks: shown, marked in the hover
Values flagged `p` (provisional, 46 rows), `e` (estimated, 2) or `b` (break
in series, 4: Austria 2022, Belgium 2009) are kept as published. The `flag`
column carries the flag into the hover. A share takes the category's flag, or
the total's flag if the category has none: the share is provisional if either
part is.

Why not use only the last fully confirmed year: countries confirm at
different times, so one "confirmed" year would be several years old and hide
the most recent data. The year slider shows every year anyway.

### D7. Country codes converted to ISO-3
Eurostat codes Greece `EL` and the UK `UK` (ISO: `GR`, `GB`). The OECD and
Plotly use ISO-3 (`GRC`, `GBR`). A hand-written lookup in
`src/country_codes.py` does the conversion (pycountry does not know
`EL`/`UK`). Kosovo (`XK`) has no official ISO code; it is mapped to `XKX`
(used by the EU and World Bank). Whether Plotly can draw it is still to be
checked. EU and euro-area aggregates are excluded because they are not
countries.

### D8. Shares computed from current-price national-currency values
`share = category (CP_MNAC) / TOTAL (CP_MNAC) * 100`, calendar years.
Eurostat also publishes the share (`PC_TOT`), but the OECD data has no
equivalent, so computing it ourselves keeps one method for all countries.
Cross-check: 2,270 shares compared with `PC_TOT`, all within rounding except
Montenegro 2007 housing (11.850 vs 11.8, exactly on the rounding edge).

### D9. Missing values kept visible; time range from 1995
The processed file has a row for every country x year x category, so gaps
show up as empty rows instead of disappearing. Counting starts in 1995
because that is when (almost) every country starts reporting; earlier years
exist only for DK, FR, FI, NO, SE and are kept in the file.

## Missing values (Eurostat, 1995-2025)
*Script: `src/check_missing_values.py`*

38 countries x 31 years = 1,178 country-years; **100 missing (8.5%)**:
85 not published, 15 frozen back-data (Romania).

- **No gaps inside any country's series.** All missing years are at the start
  or the end.
- **Late starters:** BA, MK 2000; ME 2006; XK 2008; TR 2009; RO 2010 (D3).
- **Early enders:** XK 2017, UK 2019 (left the EU's reporting), LT, MK, NO 2023.
- **Latest years are incomplete:** 2024 has 33 of 38 countries, **2025 only
  16**. A map defaulting to 2025 would look half empty, and the countries
  present would not be a random sample.
- **No imputed-rent figure for the hover:** CH (all years) and TR (all
  years), which are confidential; NO (2 years) and IT (1 year).

## Limitations (open issues, not fixed)

### L1. Imputed rent is not estimated consistently across countries
*Script: `src/investigate_imputed_rent.py` (COICOP 2018, 2022)*

- Imputed rent is 22% of housing & utilities in Poland but 72% in Hungary,
  and its share barely relates to how many people own their home
  (correlation 0.13).
- Implied imputed rent per owner vs. actual rent per tenant ranges from
  0.29 (Malta) and 0.41 (Poland) to 4.59 (Slovenia), median 1.24. Some spread
  is expected (owners' homes are often larger; "tenants" includes people
  paying reduced or no rent), but this range points to different estimation
  methods rather than different housing costs.
- Without imputed rent the housing ranking would change a lot: Poland 20th
  -> 3rd, Germany 10th -> 2nd, Hungary 18th -> 29th (among the ~30 European
  countries with data).

### L2. Totals include tourists' spending (domestic concept)
*Script: `src/investigate_tourism.py` (OECD table 5 "on the territory and abroad", 2022)*

The total counts all household spending on a country's territory, including
by foreign visitors, and excludes residents' spending abroad. Tourist spending
inflates the total, which pushes shares down. Within 5% for most countries;
on a residents-only total a 25% housing share would be: Croatia 32.4%,
Greece 27.7%, Portugal 27.6%, Luxembourg 27.3%, Iceland 26.5%, Spain 26.4%.
An upper bound for food (tourists do buy food). Malta and Cyprus are probably
affected but not in the OECD table. 2022 only.

### L3. Provisional and revised data
Recent years are often provisional (D6), and the version comparison (D2) shows
that revisions can move shares by several points.
