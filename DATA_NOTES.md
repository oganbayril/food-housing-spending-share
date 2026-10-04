# Data notes

Data-quality issues found along the way: what was found, what (if anything)
was done about it, and why. Raw material for the README limitations section.

## Open issues

### 1. Housing & utilities (CP04) is mostly *imputed* rent, at very different levels
CP04 includes imputed rent: the rent owner-occupiers would pay for their own
home. No cash changes hands, but national accounts count it so that countries
with many owners and countries with many tenants are comparable. This is why
CP04 is labelled "housing & utilities", never "rent".

Imputed rent (CP042) as a share of CP04, 2022:

| DE | EL | FR | IT | PL |
|---|---|---|---|---|
| 38.9% | 52.5% | 53.2% | 56.6% | 22.5% |

Poland stands out: imputed rent is a small part of CP04 despite a high
ownership rate, and electricity/gas/fuels (CP045) is the largest part (37.1%).
This may reflect differences in how countries estimate imputed rent rather
than real differences in housing costs. Not investigated yet; worth checking
before interpreting cross-country housing shares.

### 2. Totals use the domestic concept (spending *on the territory*)
The TOTAL denominator is household consumption on the country's territory: it
includes spending by foreign visitors and excludes residents' spending abroad.
Evidence: the German figures match the OECD table exactly, and the OECD labels
its transaction `P31DC`, "residents and non-residents on the territory".
In tourism-heavy countries (e.g. Greece) tourist spending inflates the total,
which would push the food and housing shares *down*. Size of the effect not
measured yet.

### 3. Provisional values
2022 values for DE, FR and EL are flagged `p` (provisional) and may be revised.
Kept as published, with the flag carried into the processed file.

### 4. Country codes are Eurostat codes, not ISO
Greece is `EL` (ISO: `GR`), and the UK would be `UK` (ISO: `GB`). The
processed file keeps Eurostat codes. Conversion to ISO-3 will be needed for
the Plotly map and for joining with OECD data (which uses ISO-3: `DEU`, `USA`).

### 5. OECD data is split across two COICOP versions (affects step 4)
The old OECD codes are gone. The OECD Data Explorer has two tables:
- `DSD_NAMAIN10@DF_TABLE5_T501`: COICOP 1999 (same as Eurostat)
- `DSD_NAMAIN10@DF_TABLE5A_T501`: COICOP 2018

In 2022, the USA appears only in the 1999 table and Japan only in the 2018
table. Germany is in both, with different values (total 1,876,818 vs
2,039,004 million EUR; CP04 24.6% vs 24.8% of total). Eurostat's figures match
the **1999** table exactly. Mixing the two versions would compare slightly
different definitions; a decision is needed in step 4.

## Resolved / decisions

### Shares are computed from current-price national-currency values
`share = category (CP_MNAC) / TOTAL (CP_MNAC) * 100`. Eurostat also publishes
the share directly (`PC_TOT`), but the OECD data has no equivalent, so
computing it ourselves keeps one method for all countries. `PC_TOT` is kept as
a cross-check: all 10 test values match it within rounding (max difference
0.04 points; Eurostat rounds to one decimal).

### Missing values are kept visible, not dropped
The loader builds the full country x category grid first, so a missing value
shows up as an empty row with no share instead of disappearing. None were
missing in the 2022 test.
