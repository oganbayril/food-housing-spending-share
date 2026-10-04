# food-housing-spending-share

Portfolio project (junior data analyst): share of household consumption spent on
food (COICOP CP01) and housing & utilities (CP04) across OECD + European
countries (~45), shown as a Plotly choropleth with green/yellow/red tiers and a
year slider. Benchmarked against fixed thresholds, not each country's own past.

## Decisions made (2026-10-04)

- **Repo name:** `food-housing-spending-share` (renamed from `essential-cost-burden`).
  Why: "burden" implies a share of *income*, but we measure a share of
  *consumption spending*; "essential" overclaims since health/education/transport
  are excluded on purpose.
- **Label CP04 "housing & utilities", never "rent".** It includes imputed rent
  of owner-occupiers (to verify in DATA_NOTES.md).
- **Not about** inflation accuracy or government transparency. README only says
  figures are official statistics.
- **Out of scope on purpose:** healthcare, education, wage-based measures.
- **Processed data is committed to git** (so viewers see results without running
  anything); `data/raw/` is gitignored (re-downloadable).
- **Dashboard = static site.** Python builds one self-contained Plotly HTML
  (slider runs client-side) + the processed CSV as a download. Served by Caddy
  `file_server` on the user's Hetzner VPS under a DuckDNS subdomain. No FastAPI,
  no Dash, no Streamlit. Why: data is small, static and updated annually, so no
  server process is needed (nothing to sleep or crash).
  - Deploy caveat: `germany-real-estate-api/deploy/setup.sh` overwrites
    `/etc/caddy/Caddyfile` with a single-site template. At deploy time, switch to
    a main Caddyfile that imports per-site files so the two projects don't clobber
    each other.
- **Tooling:** Python 3.13, uv (pyproject.toml) plus a requirements.txt for
  readers. pandas, plotly, requests. Branch `main`.

## Data sources (structure must be verified before building on them)

- Eurostat `nama_10_co3_p3`: household consumption by COICOP purpose (main, annual)
- OECD national accounts, household spending by COICOP (non-EU OECD members;
  dataset codes likely changed with the OECD Data Explorer move)
- Eurostat `ilc_lvho07a`: housing cost overburden rate (validation of tiers)
- Eurostat `ilc_lvho02`: owner/tenant distribution (hover context)

Verified 2026-10-04: all three Eurostat datasets exist as expected
(`nama_10_co3_p3` also publishes `PC_TOT`, used as a cross-check only). OECD
codes changed: `DSD_NAMAIN10@DF_TABLE5_T501` (COICOP 1999) and
`DSD_NAMAIN10@DF_TABLE5A_T501` (COICOP 2018), coverage split between them
(DATA_NOTES.md issue 5). Run Python via `uv run python`, never bare `python`.

Known gotcha: Eurostat uses `EL` (Greece) and `UK`, not ISO `GR`/`GB`.

## Working agreement

- Steps in order, wait for the user's confirmation between them:
  1. Project structure (data/raw, data/processed, src, notebooks, README,
     DATA_NOTES.md, requirements.txt, .gitignore).
  2. Eurostat loader for ONE year (2022) and 5 countries (DE, FR, IT, PL, EL):
     CP01, CP04, CP00 total, current prices national currency; % of total.
     Save raw and processed separately.
  3. Show results, flag data-quality issues. **Never silently fix them.** Log
     them in DATA_NOTES.md (raw material for the README limitations section).
  4. Only after confirmation: all years/countries, then OECD for non-EU members.
- Don't build the map, tiers or README until asked. Ask before expanding scope.
- Commit after each working step, then push to origin (GitHub) right away.
- User is self-taught: simple, readable pandas, no clever one-liners. Briefly
  explain WHY for each non-obvious decision so they can defend it in interviews.

## Status

- [x] Step 1: project setup
- [x] Step 2: Eurostat loader (1 year, 5 countries)
- [x] Step 3: review + DATA_NOTES.md (awaiting user confirmation)
- [ ] Step 4: all years/countries + OECD
