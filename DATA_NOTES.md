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
Result (OECD): ISR, JPN, KOR on 2018; AUS, CAN, CHL, COL, CRI, MEX, NZL, USA
on 1999.

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

OECD side: Israel is the only OECD-sourced country in both OECD versions;
its gap is small (food max 0.27, housing max 0.60 points).

**Worst cases (4+ points), candidates for hover footnotes**
(`data/processed/checks/coicop_versions_large_gaps.csv`). All five countries
use COICOP 2018 on the map; the gap can only be measured up to 2022, where
the 1999 data ends.

| Country | Measure | Years with a 4+ point gap | Largest |
|---|---|---|---|
| Latvia | housing | 2003-2008, 2012-2022 (17 years) | 6.24 (2007) |
| Romania | housing | 2013-2022 (10 years) | 7.57 (2016) |
| Czechia | housing | 2020-2022 | 6.86 (2022) |
| Montenegro | food | 2006, 2007, 2009, 2011, 2012, 2014, 2019, 2023 | 6.29 (2006) |
| Bosnia and Herzegovina | food | 2005, 2008, 2009 | 4.22 (2009) |

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

### D9. Missing values kept visible; time range 1995-2024, map opens on 2024
The processed files have a row for every country x year x category, so gaps
show up as empty rows instead of disappearing.

- Start: 1995, when (almost) every country starts reporting. Earlier years
  exist for a few countries only and are kept in the files.
- End: the year slider stops at **2024** and the map opens on it. 2025 is
  left out of the slider because only 16 of 38 European countries had
  published it (October 2026): the map would look half empty, and the
  countries present would not be a random sample. 2025 values stay in the
  processed files. (`MAP_LAST_YEAR`, `MAP_DEFAULT_YEAR` in `decisions.py`.)

### D10. One source per country: Eurostat first, OECD for the rest
`source` column: "Eurostat" or "OECD". Eurostat covers 37 European countries;
the OECD covers 12: the 11 OECD members Eurostat does not have (AUS, CAN,
CHL, COL, CRI, ISR, JPN, KOR, MEX, NZL, USA) plus the UK (D12). Same version rule (D1) and the same share
calculation (`src/shares.py`). `src/combine_sources.py` stops with an error if
a country ever appears in both sources. Countries in the OECD tables that are
not OECD members (Brazil, Hong Kong, Russia, ...) are out of scope.

OECD details:
- Values are millions of national currency (checked: `UNIT_MULT` = 6, unit
  `XDC`), current prices, transaction `P31DC` (domestic concept, same as
  Eurostat).
- OECD status codes are converted to Eurostat-style flags: `P` -> `p`,
  `E` -> `e`, `B` -> `b`, `A` (normal) -> no flag.
- 13 empty placeholder rows (series listed with no observations: CHE, JPN,
  NOR, TUR) are dropped.

### D11. Eurostat vs OECD where both publish: sources not mixed
*Script: `src/compare_eurostat_oecd.py`*

26 Eurostat countries are also in the OECD tables. Compared within the same
COICOP version:
- **21 match within rounding** (0.05 points) in every overlapping year.
- **UK: does not match.** 49 of 50 values differ; food by up to 0.89 points
  (2015), housing by about 0.5 points in most years. The totals differ by
  0.5-0.8%. **The cause is not verified.** One possible explanation is that
  Eurostat's UK series is an older vintage that stopped being updated after
  2019 while the OECD's was revised later, but nobody has checked this, so
  it must not be stated as the reason.
- **Austria** 2022-2024 housing (up to 0.24, Eurostat flags a series break
  in 2022), **Turkey** 2024 (housing 0.68), **Lithuania** 2022-2023 (up to
  0.08): small differences in recent years only, likely revisions published
  at different times.
- **Norway**: no OECD data at all (only an empty placeholder).
- **Iceland**: matches exactly, but the OECD has no years Eurostat lacks.

Extra years: the **UK is the only country where the OECD has years Eurostat
does not (2020-2025)**. Because the UK does not match within rounding, the
OECD years are not appended to the Eurostat series: that would mix two
sources within one series. See D12 for what was decided instead.

### D12. The UK's whole series comes from the OECD
Decided: the UK is taken entirely from the OECD (1995-2025), not from
Eurostat (which ends in 2019). One source for the whole series, so nothing
is mixed. (`SOURCE_OVERRIDES` in `decisions.py`; `eurostat_shares.csv` still
contains the Eurostat UK series for comparison, and `combine_sources.py`
drops it.)

Confirmed before mapping:
- **COICOP version: 1999.** The UK is not in the OECD's 2018 table, so 1999
  covers the whole series. Food and housing shares exist for all 31 years,
  with imputed rent.
- **Concept: domestic** (`P31DC`, "residents and non-residents on the
  territory"), the same as Eurostat's totals. `load_oecd.py` now stops with
  an error if any OECD row uses another transaction.
- No OECD status flags on any UK value (none marked provisional, including
  2024-2025).

Caveats:
- **The UK is the only European country sourced from the OECD.** The `source`
  column marks it, for the hover.
- **Extra uncertainty for the UK only:** where Eurostat and the OECD both
  publish UK figures (1995-2019) they differ by about **0.5 points for
  housing and up to 0.9 points for food**, with no verified cause. Treat UK
  values as carrying this extra margin on top of the version margin (D2).
- The UK's shares cannot be cross-checked against Eurostat's published
  `PC_TOT`, unlike the other European countries.

### D13. Hover footnotes for the largest version gaps
Countries and measures where the COICOP 1999 and 2018 versions differ by 4+
points in at least one year (table in D2) carry the largest gap in
`large_version_gap_pts`, for a hover footnote:
Latvia housing (6.24), Romania housing (7.57), Czechia housing (6.86),
Montenegro food (6.29), Bosnia and Herzegovina food (4.22).

The footnote applies to **every year** of that country and measure, not only
the years where a 4+ gap was measured. Why: the gap can only be measured up
to 2022 (where the 1999 data ends), and for Latvia, Romania and Czechia it is
still above 4 points in 2022, so there is no reason to assume it closed in
2023-2024, the years the map opens on.

## Missing values (both sources, 1995-2024)
*Script: `src/check_missing_values.py`*

49 countries x 30 years = 1,470 country-years; **109 missing (7.4%)**:
94 not published, 15 frozen back-data (Romania). (UK from the OECD, D12.)

- **No gaps inside any country's series.** All missing years are at the start
  or the end.
- **Late starters:** BA, MK 2000; COL 2005; ME 2006; XK 2008; TR 2009;
  RO 2010 (D3); CHL 2018.
- **Early enders:** XK 2017, CRI 2021, LT, MK, NO 2023.
- **2024 (the map's default year): 44 of 49 countries.** Missing: LT, MK,
  NO, XK, CRI.
- **No imputed-rent figure for the hover:** CH, TR (confidential), KOR, NZL,
  COL, CHL (not published), NO (2 years).

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
