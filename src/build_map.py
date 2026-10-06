"""Build the DRAFT map: essentials share tiers by country, 1995-2024.

Output:
- site/index.html        standalone page (Plotly included, works offline)
- images/map_2024.png    static image of the 2024 map, for the README

Design choices (see DATA_NOTES.md for the data decisions):
- Tiers are ORDERED (lower -> moderate -> higher), so they use one hue in
  light-to-dark steps, not green/yellow/red: the order is visible in the
  colour itself, it survives colour-blindness, and it avoids implying
  "good / bad". "No data" is a neutral grey; countries outside the project's
  scope are an even lighter land colour, so the two are not confused.
- Colours are pinned per tier (color_discrete_map) and the tier order is
  pinned (category_orders), and the script checks every animation frame, so
  a colour can never move to a different tier between years.

Run from the project root, after src/combine_sources.py:
    uv run python src/build_map.py
"""

from pathlib import Path

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

# Tier names as shown in the legend and the hover. Neutral wording.
NO_DATA = "No data"
TIER_NAMES = [
    "Lower essentials share (below 35%)",
    "Moderate essentials share (35% to 45%)",
    "Higher essentials share (45% or more)",
]
TIER_ORDER = TIER_NAMES + [NO_DATA]

# One-hue ordinal ramp (blue, light -> dark), validated with the dataviz
# validator in --ordinal mode: monotone lightness, visible steps, lightest
# step still 2:1 against the page. Grey for "No data".
TIER_COLORS = {
    TIER_NAMES[0]: "#86b6ef",
    TIER_NAMES[1]: "#2a78d6",
    TIER_NAMES[2]: "#104281",
    NO_DATA: "#c3c2b7",
}
SURFACE = "#fcfcfb"
OUT_OF_SCOPE_LAND = "#f0efec"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"

FLAG_NAMES = {"p": "provisional", "e": "estimated", "b": "break in series"}

COVID_YEARS = [2020, 2021]
COVID_NOTE = (
    "Note for {year}: higher shares across many countries likely reflect lower "
    "spending on restaurants, travel and leisure during COVID-19 (cause not verified)."
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
        return "<br>".join(lines)

    # Up front: tier and the three shares.
    lines.append(f"Tier: <b>{tier}</b>")
    lines.append(f"Essentials: <b>{food['essentials_share']:.1f}%</b> of household spending")
    lines.append(f"&nbsp;&nbsp;Food & non-alcoholic beverages: {food['share_pct']:.1f}%")
    lines.append(f"&nbsp;&nbsp;Housing & utilities (incl. imputed rent): {housing['share_pct']:.1f}%")
    if pd.notna(housing["imputed_rent_share_pct"]):
        lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;of which imputed rent: {housing['imputed_rent_share_pct']:.1f}%")
    else:
        lines.append("&nbsp;&nbsp;&nbsp;&nbsp;of which imputed rent: not published")

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
    return "<br>".join(lines)


def country_year_table():
    """One row per country and map year, including years with no data."""
    shares = pd.read_csv(PROCESSED_DIR / "shares.csv")
    shares = shares[(shares["year"] >= FIRST_YEAR) & (shares["year"] <= MAP_LAST_YEAR)]

    rows = []
    for (iso3, year), group in shares.groupby(["iso3", "year"]):
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


def frame_annotations(year):
    """Notes shown inside the map for a given year (COVID years only)."""
    if year not in COVID_YEARS:
        return []
    return [
        # Top-left, inside the plot area (below the map it gets clipped).
        dict(
            text=COVID_NOTE.format(year=year).replace(" during", "<br>during"),
            x=0.01, y=0.99, xref="paper", yref="paper",
            xanchor="left", yanchor="top", align="left", showarrow=False,
            bgcolor="rgba(252,252,251,0.85)",
            font=dict(size=12, color=TEXT_SECONDARY),
        )
    ]


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

    # Hover and borders, on the visible traces AND inside every frame
    # (frames carry their own copies of the traces).
    trace_style = dict(
        hovertemplate="%{customdata[0]}<extra></extra>",
        marker_line_color=SURFACE,
        marker_line_width=0.6,
    )
    fig.update_traces(**trace_style)
    for frame in fig.frames:
        for trace in frame.data:
            trace.update(**trace_style)
        frame.layout = go.Layout(annotations=frame_annotations(int(frame.name)))

    fig.update_geos(
        resolution=50,  # the default 110m map has no Malta
        projection_type="natural earth",
        showcountries=True,
        countrycolor=SURFACE,
        showland=True,
        landcolor=OUT_OF_SCOPE_LAND,
        showcoastlines=False,
        showocean=False,
        showlakes=False,
        showframe=False,
        bgcolor=SURFACE,
        lonaxis_range=WORLD_VIEW["geo.lonaxis.range"],
        lataxis_range=WORLD_VIEW["geo.lataxis.range"],
    )
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=TEXT_PRIMARY),
        margin=dict(l=10, r=10, t=10, b=10),
        height=620,
        # Legend stacked in the empty South Pacific, so it never collides
        # with the World / Europe buttons and all four entries stay visible.
        legend=dict(
            title=dict(text="Food + housing & utilities,<br>% of household spending"),
            orientation="v", x=0.01, y=0.08, xanchor="left", yanchor="bottom",
            bgcolor="rgba(252,252,251,0.85)",
        ),
        hoverlabel=dict(bgcolor="#ffffff", font_size=13, align="left"),
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
        x=1.0, y=1.02, xanchor="right", yanchor="bottom",
        showactive=True,
        active=0,
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
    for visible, frame_trace in zip(fig.data, fig.frames[index].data):
        visible.update(frame_trace)
    fig.layout.sliders[0].active = index
    fig.layout.annotations = frame_annotations(year)


def check_colors_fixed(fig):
    """Stop if any frame has the tiers in a different order or colour.

    Plotly matches traces between frames by position. If one year lacked a
    tier, the traces would shift and colours would jump between tiers.
    """
    for frame in fig.frames:
        names = [trace.name for trace in frame.data]
        if names != TIER_ORDER:
            raise ValueError(f"Frame {frame.name}: tier traces {names}")
    for trace in fig.data:
        if trace.colorscale[0][1] != TIER_COLORS[trace.name]:
            raise ValueError(f"Trace {trace.name} has colour {trace.colorscale[0][1]}")
    print(f"Colour check: all {len(fig.frames)} frames have the 4 tiers in the same order and colour.")


def page_html(fig, table):
    """Wrap the figure in a small standalone page with title and notes."""
    figure_html = fig.to_html(include_plotlyjs=True, full_html=False, auto_play=False)
    latest = table[table["year"] == MAP_DEFAULT_YEAR]
    n_data = (latest["tier"] != NO_DATA).sum()
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Food & Housing Spending Share</title>
<style>
  :root {{ --surface: {SURFACE}; --text: {TEXT_PRIMARY}; --text-2: {TEXT_SECONDARY}; }}
  body {{ margin: 0; background: var(--surface); color: var(--text);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
  h1 {{ font-size: 1.5rem; margin: 0.5rem 0 0.25rem; }}
  .lede {{ color: var(--text-2); margin: 0 0 0.75rem; }}
  .draft {{ display: inline-block; font-size: 0.8rem; padding: 2px 8px;
           border: 1px solid #c3c2b7; border-radius: 4px; color: var(--text-2); }}
  ul {{ color: var(--text-2); font-size: 0.9rem; padding-left: 1.2rem; }}
</style>
</head>
<body>
<main>
<span class="draft">Draft</span>
<h1>How much of household spending goes to food and housing</h1>
<p class="lede">Food and housing &amp; utilities as a share of household consumption spending,
{FIRST_YEAR}-{MAP_LAST_YEAR}, OECD and European countries. Tiers use fixed thresholds
({TIER_THRESHOLDS[0]}% and {TIER_THRESHOLDS[1]}%), the same for every country and year.
{MAP_DEFAULT_YEAR}: {n_data} of {len(latest)} countries have data.</p>
{figure_html}
<ul>
  <li>Official statistics from Eurostat and the OECD. A share of <em>spending</em>, not of income:
      not an affordability or overburden measure.</li>
  <li>Housing &amp; utilities includes imputed rent (what owner-occupiers would pay to rent
      their own home), which countries estimate in different ways.</li>
  <li>Grey: in scope but no data for that year. Lighter land: outside this project's scope.</li>
  <li>Kosovo: the base map draws Kosovo's territory as part of Serbia, so that area shows
      Serbia's colour and data. Kosovo's own figures (2008-2017) are in the data download
      but cannot be shown on the map.</li>
  <li>{MAP_LAST_YEAR + 1} is not shown: too few countries had published it.</li>
</ul>
</main>
</body>
</html>
"""


def save_png(fig, path):
    """Static image of the map as it opens (no slider or buttons)."""
    static = go.Figure(data=fig.data, layout=fig.layout)
    # Assign (not update_layout): update_layout merges and would keep them.
    static.layout.sliders = ()
    static.layout.updatemenus = ()
    static.update_layout(width=1200, height=620)
    static.write_image(path, scale=2)


def main():
    table = country_year_table()
    fig = build_figure(table)
    check_colors_fixed(fig)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    html_path = SITE_DIR / "index.html"
    html_path.write_text(page_html(fig, table), encoding="utf-8")
    print(f"Saved {html_path} ({html_path.stat().st_size / 1e6:.1f} MB)")

    png_path = IMAGES_DIR / f"map_{MAP_DEFAULT_YEAR}.png"
    save_png(fig, png_path)
    print(f"Saved {png_path}")

    latest = table[table["year"] == MAP_DEFAULT_YEAR]
    print(f"\n{MAP_DEFAULT_YEAR} on the map:")
    print(latest["tier"].value_counts().reindex(TIER_ORDER, fill_value=0).to_string())


if __name__ == "__main__":
    main()
