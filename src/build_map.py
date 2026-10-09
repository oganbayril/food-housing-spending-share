"""Build the DRAFT map: essentials share tiers by country, 1995-2024.

Output:
- site/index.html               standalone page (Plotly included; the map outlines
                                are loaded from Plotly's CDN, so it needs internet)
- site/shares.csv               the processed data, as a download
- site/favicon.svg              small icon (avoids a favicon.ico 404)
- images/map_2024.png           static image, world view (README)
- images/map_2024_europe.png    static image, Europe view (README)

Design choices (see DATA_NOTES.md for the data decisions):
- Tiers are ORDERED (lower -> moderate -> higher), so they use one hue in
  light-to-dark steps, not green/yellow/red: the order is visible in the
  colour itself, it survives colour-blindness, and it avoids implying
  "good / bad". "No data" is a neutral grey; countries outside the project's
  scope are a plainer land colour, so the two are not confused.
- Colours are pinned per tier (color_discrete_map) and the tier order is
  pinned (category_orders). The script checks every animation frame, so a
  colour can never move to a different tier between years.
- Dark mode: the page follows the reader's system setting. On a dark
  background the ramp runs the other way (lower = darkest blue, higher =
  lightest), so higher shares stand out in both modes. Both ramps were
  validated with the dataviz palette validator (--ordinal).
- Kosovo: the base map has no Kosovo shape and draws its territory as part of
  Serbia (DATA_NOTES L4). Kosovo rows are kept OUT of the map, and the
  script checks that Serbia's colour and hover come from Serbia's data only.

Run from the project root, after src/combine_sources.py:
    uv run python src/build_map.py
"""

import base64
import hashlib
import json
import re
import shutil

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from country_codes import ISO3_NAMES
from decisions import (
    FIRST_YEAR,
    MAP_DEFAULT_YEAR,
    MAP_LAST_YEAR,
    NEAR_BOUNDARY_MARGIN,
    TIER_THRESHOLDS,
)
from sources import PROCESSED_DIR, PROJECT_ROOT
from tier_checks import assign_tier

SITE_DIR = PROJECT_ROOT / "site"
IMAGES_DIR = PROJECT_ROOT / "images"

# Countries in the data that the base map cannot draw (DATA_NOTES L4).
NOT_MAPPABLE = {"XKX"}
SERBIA_MAP_NOTE = (
    "Map note: on this base map Serbia's shape also covers Kosovo;<br>"
    "Kosovo's own figures are not shown"
)

# Tier names as shown in the legend and the hover. Neutral wording, with the
# thresholds in the name so the legend states them.
NO_DATA = "No data"
TIER_NAMES = [
    f"Lower essentials share (below {TIER_THRESHOLDS[0]}%)",
    f"Moderate essentials share ({TIER_THRESHOLDS[0]}% to {TIER_THRESHOLDS[1]}%)",
    f"Higher essentials share ({TIER_THRESHOLDS[1]}% or more)",
]
TIER_ORDER = TIER_NAMES + [NO_DATA]
LEGEND_TITLE = (
    "<b>Essentials share</b>: food + housing & utilities<br>"
    "as a % of household consumption spending"
)

# Colours per theme. Light: the validated ramp light -> dark. Dark: the same
# hue, validated against the dark surface, darkest step for "lower".
THEMES = {
    "light": {
        "tiers": ["#86b6ef", "#2a78d6", "#104281"],
        "no_data": "#c3c2b7",
        "surface": "#fcfcfb",
        "land": "#f0efec",
        "text": "#0b0b0b",
        "text_2": "#52514e",
        "control_bg": "#ffffff",
        "border": "#c3c2b7",
    },
    "dark": {
        "tiers": ["#184f95", "#3987e5", "#9ec5f4"],
        "no_data": "#898781",
        "surface": "#1a1a19",
        "land": "#2c2c2a",
        "text": "#ffffff",
        "text_2": "#c3c2b7",
        "control_bg": "#262624",
        "border": "#383835",
    },
}
LIGHT = THEMES["light"]
TIER_COLORS = {
    TIER_NAMES[0]: LIGHT["tiers"][0],
    TIER_NAMES[1]: LIGHT["tiers"][1],
    TIER_NAMES[2]: LIGHT["tiers"][2],
    NO_DATA: LIGHT["no_data"],
}

FLAG_NAMES = {"p": "provisional", "e": "estimated", "b": "break in series"}

COVID_YEARS = [2020, 2021]
COVID_NOTE = (
    "Note for {year}: higher shares across many countries likely reflect lower "
    "spending on restaurants, travel and leisure during COVID-19 (cause not verified)."
)

# Plotly toolbar: keep download-as-PNG, pan, zoom, reset. Remove "Share
# chart..." (sendChartToCloud), which uploads the chart to Plotly Cloud, the
# select/lasso tools (meaningless on a map) and the Plotly logo.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["sendChartToCloud", "select2d", "lasso2d"],
}

# Content-Security-Policy, the narrowest that works (tested in Edge and
# Firefox, light and dark, with every interaction; see deploy/PLAN.md):
# - scripts: only the page's own inline scripts, by hash (filled in at build)
# - styles: 'unsafe-inline', because Plotly sets style="..." attributes and
#   injects <style> elements at runtime (static page, no user input)
# - images: same origin (favicon) and blob: (Plotly's PNG export)
# - connections: Plotly's CDN, which serves the map outlines
CSP_TEMPLATE = (
    "default-src 'none'; "
    "script-src {script_hashes}; "
    "style-src 'unsafe-inline'; "
    "img-src 'self' blob:; "
    "connect-src https://cdn.plot.ly; "
    "base-uri 'none'; "
    "form-action 'none'"
)

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<rect width="16" height="16" rx="3" fill="#2a78d6"/>'
    '<rect x="3" y="9" width="3" height="4" fill="#cde2fb"/>'
    '<rect x="7" y="6" width="3" height="7" fill="#cde2fb"/>'
    '<rect x="11" y="3" width="2" height="10" fill="#cde2fb"/>'
    "</svg>\n"
)

# Map extents for the World / Europe buttons (longitude and latitude ranges).
WORLD_VIEW = {"geo.lonaxis.range": [-180, 180], "geo.lataxis.range": [-58, 85]}
EUROPE_VIEW = {"geo.lonaxis.range": [-25, 45], "geo.lataxis.range": [34, 71]}


def tier_name(essentials):
    if pd.isna(essentials):
        return NO_DATA
    return TIER_NAMES[assign_tier(essentials, TIER_THRESHOLDS)]


def describe_flags(food, housing):
    """Flags on either category, in words. The UK note follows D12."""
    flags = []
    for flag in [food["flag"], housing["flag"]]:
        if pd.notna(flag):
            for letter in str(flag):
                name = FLAG_NAMES.get(letter, letter)
                if name not in flags:
                    flags.append(name)
    if flags:
        return ", ".join(flags)
    if food["source"] == "OECD":
        return "none published (the OECD publishes no provisional flags here)"
    return "none"


def build_hover(food, housing, name, tier):
    """Hover text for one country-year, as HTML lines."""
    year = int(food["year"])
    lines = [f"<b>{name}</b>, {year}"]

    if tier == NO_DATA:
        if food["frozen_back_data"]:
            lines.append("No data: published values for 1995-2009 were estimated")
            lines.append("with a fixed spending structure, so they are not shown")
        else:
            lines.append("No data for this year")
    else:
        # Up front: tier and the three shares.
        indent = "&nbsp;&nbsp;"
        lines.append(f"Tier: <b>{tier}</b>")
        lines.append(f"Essentials: <b>{food['essentials_share']:.1f}%</b> of household spending")
        lines.append(f"{indent}Food & non-alcoholic beverages: {food['share_pct']:.1f}%")
        lines.append(f"{indent}Housing & utilities (incl. imputed rent): {housing['share_pct']:.1f}%")
        if pd.notna(housing["imputed_rent_share_pct"]):
            lines.append(f"{indent}{indent}of which imputed rent: {housing['imputed_rent_share_pct']:.1f}%")
        else:
            lines.append(f"{indent}{indent}of which imputed rent: not published")

        # Provenance.
        lines.append(f"Source: {food['source']} (COICOP {int(food['coicop_version'])})")
        lines.append(f"Flags: {describe_flags(food, housing)}")

        # Only where they apply.
        if food["near_tier_boundary"]:
            lines.append(
                f"Within {NEAR_BOUNDARY_MARGIN:g} point of a tier boundary "
                f"({TIER_THRESHOLDS[0]}% / {TIER_THRESHOLDS[1]}%)"
            )
        if food["high_tourism"]:
            lines.append("Tourist spending is included in the total and lowers these shares")
        for row, label in [(food, "Food"), (housing, "Housing")]:
            if pd.notna(row["version_gap_note"]):
                lines.append(f"{label}: {row['version_gap_note']}")

    if food["iso3"] == "SRB":
        lines.append(SERBIA_MAP_NOTE)
    return "<br>".join(lines)


def country_year_table():
    """One row per mappable country and map year, including years with no data."""
    shares = pd.read_csv(PROCESSED_DIR / "shares.csv")
    shares = shares[(shares["year"] >= FIRST_YEAR) & (shares["year"] <= MAP_LAST_YEAR)]

    rows = []
    for (iso3, year), group in shares.groupby(["iso3", "year"]):
        if iso3 in NOT_MAPPABLE:
            continue  # kept in shares.csv, never sent to the map
        food = group[group["coicop"] == "CP01"].iloc[0]
        housing = group[group["coicop"] == "CP04"].iloc[0]
        name = ISO3_NAMES[iso3]
        tier = tier_name(food["essentials_share"])
        rows.append(
            {
                "iso3": iso3,
                "year": int(year),
                "tier": tier,
                "hover": build_hover(food, housing, name, tier),
            }
        )
    return pd.DataFrame(rows)


def build_figure(table):
    years = sorted(table["year"].unique())
    fig = px.choropleth(
        table,
        locations="iso3",
        color="tier",
        animation_frame="year",
        color_discrete_map=TIER_COLORS,
        category_orders={"tier": TIER_ORDER, "year": years},
        custom_data=["hover"],
    )
    fig.update_traces(
        hovertemplate="%{customdata[0]}<extra></extra>",
        marker_line_color=LIGHT["surface"],
        marker_line_width=0.6,
    )

    # Frames carry only what changes between years (which countries are in
    # which tier, and their hover text). Colours live on the visible traces
    # only, so switching to dark mode recolours every year, not just the
    # current one.
    #
    # Every frame also gets all four tiers, in the same order. Plotly matches
    # traces between frames by POSITION: if a year had no "No data" country,
    # plotly express would leave that trace out, and the previous year's grey
    # countries would stay on screen. An empty trace clears them instead.
    for frame in fig.frames:
        by_name = {}
        for trace in frame.data:
            by_name[trace.name] = trace
        slim = []
        for name in TIER_ORDER:
            if name in by_name:
                trace = by_name[name]
                slim.append(
                    go.Choropleth(
                        name=name,
                        locations=trace.locations,
                        z=trace.z,
                        customdata=trace.customdata,
                    )
                )
            else:
                slim.append(go.Choropleth(name=name, locations=[], z=[], customdata=[]))
        frame.data = slim

    fig.update_geos(
        resolution=50,  # the default 110m map has no Malta
        projection_type="natural earth",
        showcountries=True,
        countrycolor=LIGHT["surface"],
        showland=True,
        landcolor=LIGHT["land"],
        showcoastlines=False,
        showocean=False,
        showlakes=False,
        showframe=False,
        bgcolor=LIGHT["surface"],
        lonaxis_range=WORLD_VIEW["geo.lonaxis.range"],
        lataxis_range=WORLD_VIEW["geo.lataxis.range"],
    )
    fig.update_layout(
        paper_bgcolor=LIGHT["surface"],
        plot_bgcolor=LIGHT["surface"],
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=LIGHT["text"]),
        margin=dict(l=10, r=10, t=10, b=10),
        height=620,
        # Legend stacked in the empty South Pacific, so it never collides
        # with the World / Europe buttons and all four entries stay visible.
        legend=dict(
            title=dict(text=LEGEND_TITLE),
            orientation="v", x=0.01, y=0.06, xanchor="left", yanchor="bottom",
            bgcolor="rgba(252,252,251,0.85)",
        ),
        hoverlabel=dict(bgcolor=LIGHT["control_bg"], font_size=13, align="left"),
    )

    # Choropleth frames must be fully redrawn when the year changes.
    for menu in fig.layout.updatemenus:
        for button in menu.buttons:
            if button.args and len(button.args) > 1 and isinstance(button.args[1], dict):
                button.args[1]["frame"]["redraw"] = True
    for step in fig.layout.sliders[0].steps:
        step.args[1]["frame"]["redraw"] = True
    fig.layout.sliders[0].currentvalue.prefix = "Year: "

    # World / Europe buttons (zoom the map; they do not change the data).
    zoom_menu = dict(
        type="buttons",
        direction="left",
        x=1.0, y=1.0, xanchor="right", yanchor="top",
        # No "selected" highlight: Plotly draws it in a fixed near-white that
        # hides the label in dark mode.
        showactive=False,
        buttons=[
            dict(label="World", method="relayout", args=[WORLD_VIEW]),
            dict(label="Europe", method="relayout", args=[EUROPE_VIEW]),
        ],
    )
    fig.update_layout(updatemenus=list(fig.layout.updatemenus) + [zoom_menu])

    open_on_year(fig, MAP_DEFAULT_YEAR)
    return fig


def open_on_year(fig, year):
    """Show `year` when the page loads (Plotly starts on the first frame)."""
    names = [frame.name for frame in fig.frames]
    index = names.index(str(year))
    if [trace.name for trace in fig.data] != TIER_ORDER:
        raise ValueError("Visible traces are not in tier order")
    for visible, frame_trace in zip(fig.data, fig.frames[index].data):
        visible.locations = frame_trace.locations
        visible.z = frame_trace.z
        visible.customdata = frame_trace.customdata
    fig.layout.sliders[0].active = index


def check_colors_fixed(fig):
    """Stop if any frame could put a colour on the wrong tier.

    Plotly matches traces between frames by position. If one year lacked a
    tier, the traces would shift and colours would jump between tiers. And
    frames must not carry colours of their own (dark mode sets them once).
    """
    for frame in fig.frames:
        names = [trace.name for trace in frame.data]
        if names != TIER_ORDER:
            raise ValueError(f"Frame {frame.name}: tier traces {names}")
        for trace in frame.data:
            if trace.colorscale is not None:
                raise ValueError(f"Frame {frame.name}: trace carries its own colours")
    for trace in fig.data:
        if trace.colorscale[0][1] != TIER_COLORS[trace.name]:
            raise ValueError(f"Trace {trace.name} has colour {trace.colorscale[0][1]}")
    print(f"Colour check: all {len(fig.frames)} frames have the 4 tiers in the same order; "
          f"colours are set once per tier.")


def check_kosovo_isolated(fig, table):
    """Kosovo must never reach the map, and Serbia must show only Serbia.

    For every frame: no XKX anywhere; SRB appears exactly once; its tier is
    Serbia's own tier and its hover is Serbia's own hover for that year.
    """
    serbia = table[table["iso3"] == "SRB"].set_index("year")
    for frame in fig.frames:
        year = int(frame.name)
        serbia_hits = []
        for trace in frame.data:
            for position, location in enumerate(trace.locations):
                if location in NOT_MAPPABLE:
                    raise ValueError(f"{year}: {location} is on the map")
                if location == "SRB":
                    serbia_hits.append((trace.name, trace.customdata[position][0]))
        if len(serbia_hits) != 1:
            raise ValueError(f"{year}: Serbia appears {len(serbia_hits)} times")
        tier, hover = serbia_hits[0]
        if tier != serbia.loc[year, "tier"] or hover != serbia.loc[year, "hover"]:
            raise ValueError(f"{year}: Serbia's colour or hover is not Serbia's own")
        if "<b>Serbia</b>" not in hover or "Kosovo</b>" in hover:
            raise ValueError(f"{year}: unexpected country name in Serbia's hover")
    print(f"Kosovo check: XKX in none of {len(fig.frames)} frames; Serbia appears once per "
          f"frame with its own tier and hover.")


def theme_payload():
    """The colours the page script needs to switch between light and dark."""
    payload = {}
    for mode, theme in THEMES.items():
        scales = []
        for color in theme["tiers"] + [theme["no_data"]]:
            scales.append([[0, color], [1, color]])
        payload[mode] = {
            "scales": scales,
            "layout": {
                "paper_bgcolor": theme["surface"],
                "plot_bgcolor": theme["surface"],
                "font.color": theme["text"],
                "geo.bgcolor": theme["surface"],
                "geo.landcolor": theme["land"],
                "geo.countrycolor": theme["surface"],
                "legend.bgcolor": theme["surface"],
                "hoverlabel.bgcolor": theme["control_bg"],
                "hoverlabel.font.color": theme["text"],
                "hoverlabel.bordercolor": theme["border"],
                "sliders[0].bgcolor": theme["control_bg"],
                "sliders[0].bordercolor": theme["border"],
                "sliders[0].font.color": theme["text"],
                "sliders[0].currentvalue.font.color": theme["text"],
                "updatemenus[0].bgcolor": theme["control_bg"],
                "updatemenus[0].bordercolor": theme["border"],
                "updatemenus[0].font.color": theme["text"],
                "updatemenus[1].bgcolor": theme["control_bg"],
                "updatemenus[1].bordercolor": theme["border"],
                "updatemenus[1].font.color": theme["text"],
            },
            "border": theme["surface"],
        }
    return payload


def page_html(fig, table):
    """Wrap the figure in a small standalone page with caption, notes and script."""
    # post_script runs once Plotly has finished drawing the map (including
    # loading the map outlines). Theming before that point gets overwritten.
    figure_html = fig.to_html(
        include_plotlyjs=True,
        full_html=False,
        auto_play=False,
        div_id="map",
        post_script="window.mapDrawn = true; if (window.initMap) { window.initMap(); }",
        config=PLOTLY_CONFIG,
    )
    latest = table[table["year"] == MAP_DEFAULT_YEAR]
    n_data = (latest["tier"] != NO_DATA).sum()
    light = THEMES["light"]
    dark = THEMES["dark"]
    covid = {str(year): COVID_NOTE.format(year=year) for year in COVID_YEARS}
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Food & Housing Spending Share</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>
  :root {{ --surface: {light['surface']}; --text: {light['text']}; --text-2: {light['text_2']};
          --border: {light['border']}; color-scheme: light; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{ --surface: {dark['surface']}; --text: {dark['text']};
          --text-2: {dark['text_2']}; --border: {dark['border']}; color-scheme: dark; }}
  }}
  :root[data-theme="dark"] {{ --surface: {dark['surface']}; --text: {dark['text']};
          --text-2: {dark['text_2']}; --border: {dark['border']}; color-scheme: dark; }}
  body {{ margin: 0; background: var(--surface); color: var(--text);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
  h1 {{ font-size: 1.5rem; margin: 0.5rem 0 0.25rem; }}
  .lede, .caption {{ color: var(--text-2); margin: 0 0 0.75rem; }}
  .caption {{ font-size: 0.9rem; }}
  .draft {{ display: inline-block; font-size: 0.8rem; padding: 2px 8px;
           border: 1px solid var(--border); border-radius: 4px; color: var(--text-2); }}
  .year-note {{ min-height: 1.4em; font-size: 0.9rem; color: var(--text-2); margin: 0.25rem 0; }}
  ul {{ color: var(--text-2); font-size: 0.9rem; padding-left: 1.2rem; }}
  a {{ color: inherit; }}
</style>
</head>
<body>
<main>
<span class="draft">Draft</span>
<h1>How much of household spending goes to food and housing</h1>
<p class="lede">Food and housing &amp; utilities as a share of household consumption spending,
{FIRST_YEAR}-{MAP_LAST_YEAR}, OECD and European countries.
{MAP_DEFAULT_YEAR}: {n_data} of {len(latest)} mapped countries have data.</p>
<p class="caption"><strong>What the tiers measure:</strong> the essentials share, i.e. spending on
food &amp; non-alcoholic beverages plus housing &amp; utilities (incl. imputed rent), as a % of
total household consumption spending. Fixed thresholds, the same for every country and year:
<strong>lower</strong> below {TIER_THRESHOLDS[0]}%, <strong>moderate</strong>
{TIER_THRESHOLDS[0]}% to {TIER_THRESHOLDS[1]}%, <strong>higher</strong> {TIER_THRESHOLDS[1]}% or more.
A share of spending, not of income.</p>
<p class="year-note" id="year-note" aria-live="polite"></p>
{figure_html}
<ul>
  <li>Official statistics from Eurostat and the OECD.
      <a href="shares.csv" download>Download the data (CSV)</a>.</li>
  <li>Not an affordability or overburden measure: it compares spending shares, not costs
      against income.</li>
  <li>Housing &amp; utilities includes imputed rent (what owner-occupiers would pay to rent
      their own home), which countries estimate in different ways.</li>
  <li>Grey: in scope but no data for that year. Plain land: outside this project's scope.</li>
  <li>Kosovo: the base map draws Kosovo's territory as part of Serbia, so that area shows
      Serbia's colour and data. Kosovo's own figures (2008-2017) are in the data download
      but cannot be shown on the map.</li>
  <li>Very small countries (Malta, Luxembourg, Cyprus) are only a few pixels wide; use the
      Europe view and hover to read them.</li>
  <li>{MAP_LAST_YEAR + 1} is not shown: too few countries had published it.</li>
</ul>
</main>
<script>
(function () {{
  const map = document.getElementById("map");
  const note = document.getElementById("year-note");
  const themes = {json.dumps(theme_payload())};
  const covidNotes = {json.dumps(covid)};
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

  // Note above the map for the years that need one (COVID years).
  function showYearNote(year) {{
    note.textContent = covidNotes[String(year)] || "";
  }}

  // Recolour the map for light or dark mode. Frames carry no colours, so
  // this one change holds for every year on the slider.
  function applyTheme() {{
    const forced = document.documentElement.getAttribute("data-theme");
    const mode = forced || (darkQuery.matches ? "dark" : "light");
    const theme = themes[mode];
    const traceIndices = [0, 1, 2, 3];
    Plotly.restyle(map, {{ colorscale: theme.scales, "marker.line.color": theme.border }}, traceIndices);
    Plotly.relayout(map, theme.layout);
  }}

  map.on("plotly_sliderchange", function (event) {{ showYearNote(event.step.label); }});
  map.on("plotly_animatingframe", function (event) {{ showYearNote(event.name); }});
  darkQuery.addEventListener("change", applyTheme);

  // Called by Plotly once the map is drawn (post_script above).
  window.initMap = function () {{
    showYearNote({MAP_DEFAULT_YEAR});
    applyTheme();
  }};
  // Whichever finishes last (Plotly drawing, or this script) starts it.
  if (window.mapDrawn) {{ window.initMap(); }}
}})();
</script>
</body>
</html>
"""


def inline_scripts(page):
    """The text of every inline <script> in the page, as the browser sees it."""
    return re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", page, flags=re.DOTALL)


def script_hash(text):
    """CSP hash source for one inline script: 'sha256-<base64 of SHA-256>'."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def add_csp_meta(page):
    """Insert the Content-Security-Policy as the FIRST element in <head>.

    Scripts are allowed by hash, not 'unsafe-inline'. The hashes are computed
    here from this very page, so they can never go out of date when the data
    (and therefore the figure script) changes. frame-ancestors cannot be set
    in a <meta> policy; Caddy sends it as a header instead.
    """
    hashes = []
    for text in inline_scripts(page):
        hashes.append(script_hash(text))
    policy = CSP_TEMPLATE.format(script_hashes=" ".join(hashes))
    meta = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
    if page.count("<head>\n") != 1:
        raise ValueError("Expected exactly one <head>")
    return page.replace("<head>\n", f"<head>\n{meta}\n", 1)


def check_csp_meta(page):
    """Stop the build unless the CSP meta is first in <head> and covers every script."""
    head = page.split("<head>\n", 1)[1]
    first_element = head.split("\n", 1)[0]
    if not first_element.startswith('<meta http-equiv="Content-Security-Policy"'):
        raise ValueError(f"CSP meta is not the first element in <head>: {first_element[:80]}")
    for text in inline_scripts(page):
        if script_hash(text) not in first_element:
            raise ValueError("An inline script is not covered by the CSP hashes")
    print(f"CSP check: <meta> is first in <head>; all {len(inline_scripts(page))} inline "
          f"scripts are allowed by hash.")


def save_png(fig, path, view):
    """Static image of the map as it opens (no slider or buttons)."""
    static = go.Figure(data=fig.data, layout=fig.layout)
    # Assign (not update_layout): update_layout merges and would keep them.
    static.layout.sliders = ()
    static.layout.updatemenus = ()
    static.update_layout(
        width=1200,
        height=620,
        geo=dict(lonaxis_range=view["geo.lonaxis.range"], lataxis_range=view["geo.lataxis.range"]),
    )
    static.write_image(path, scale=2)


def main():
    table = country_year_table()
    fig = build_figure(table)
    check_colors_fixed(fig)
    check_kosovo_isolated(fig, table)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    html_path = SITE_DIR / "index.html"
    page = add_csp_meta(page_html(fig, table))
    check_csp_meta(page)
    # newline="\n": the same bytes on every OS (Windows would write \r\n).
    html_path.write_text(page, encoding="utf-8", newline="\n")
    print(f"Saved {html_path} ({html_path.stat().st_size / 1e6:.1f} MB)")

    (SITE_DIR / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8", newline="\n")

    shutil.copyfile(PROCESSED_DIR / "shares.csv", SITE_DIR / "shares.csv")
    print(f"Copied shares.csv to {SITE_DIR}")

    for suffix, view in [("", WORLD_VIEW), ("_europe", EUROPE_VIEW)]:
        png_path = IMAGES_DIR / f"map_{MAP_DEFAULT_YEAR}{suffix}.png"
        save_png(fig, png_path, view)
        print(f"Saved {png_path}")

    latest = table[table["year"] == MAP_DEFAULT_YEAR]
    print(f"\n{MAP_DEFAULT_YEAR} on the map:")
    print(latest["tier"].value_counts().reindex(TIER_ORDER, fill_value=0).to_string())


if __name__ == "__main__":
    main()
