"""Build the map page: essentials share tiers by country, 1995-2024.

Output:
- site/index.html               standalone page (Plotly included; the map outlines
                                are loaded from Plotly's CDN, so it needs internet)
- site/shares.csv               the processed data, as a download
- site/favicon.svg              small icon (avoids a favicon.ico 404)
- images/map_2024.png           static image, world view, light theme (README)
- images/map_2024_europe.png    static image, Europe view, light theme (README)

Design choices (see DATA_NOTES.md for the data decisions):
- Tiers are ORDERED (lower -> moderate -> higher), so they use one hue in
  light-to-dark steps, not green/yellow/red: the order is visible in the
  colour itself, it survives colour-blindness, and it avoids implying
  "good / bad". "No data" is a neutral grey; countries outside the project's
  scope are a plainer land colour, so the two are not confused.
- The figure is built with plotly.graph_objects, not plotly.express, so the
  frames, legend and controls are fully under this script's control:
  * traces 0-3: the countries, one choropleth per tier (colour set once);
  * traces 4-7: permanent legend entries (empty Scattergeo traces), so the
    legend shows all four tiers in every year, even years without a tier;
  * frames change only traces 0-3 (locations + hover text), never colours
    and never the layout, so the year slider and Play keep the current view
    and the current theme.
- Themes: System / Light / Dark toggle in the page header, remembered in
  localStorage. On a dark background the ramp runs the other way (lower =
  darkest blue, higher = lightest), so higher shares stand out in both.
  Both ramps were validated with the dataviz palette validator (--ordinal).
- Views: World and Europe presets set the whole view (scale, centre and
  rotation). Scroll zoom is on but clamped by a small relayout listener:
  never zoomed out beyond World, no dragging at World scale, and when zoomed
  in, panning is limited so the map cannot leave the frame.
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

# Tier names. Long ones in the legend, short ones in the hover.
LOW, HIGH = TIER_THRESHOLDS
NO_DATA = "No data"
TIER_NAMES = [
    f"Lower essentials share (below {LOW}%)",
    f"Moderate essentials share ({LOW}% to {HIGH}%)",
    f"Higher essentials share ({HIGH}% or more)",
]
TIER_SHORT = [f"Lower (below {LOW}%)", f"Moderate ({LOW}-{HIGH}%)", f"Higher ({HIGH}%+)"]
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
        "legend_bg": "rgba(252,252,251,0.85)",
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
        "legend_bg": "rgba(26,26,25,0.85)",
    },
}
LIGHT = THEMES["light"]


def tier_colors(theme):
    """Colours in TIER_ORDER for one theme."""
    return theme["tiers"] + [theme["no_data"]]


FLAG_NAMES = {"p": "Provisional", "e": "Estimated", "b": "Break in series"}

COVID_YEARS = [2020, 2021]
COVID_NOTE = (
    "Note for {year}: higher shares across many countries likely reflect lower "
    "spending on restaurants, travel and leisure during COVID-19 (cause not verified)."
)

# Views. Lon/lat ranges stay at the world; a view is scale + centre (+ the
# matching rotation, which is how Plotly pans this projection). Scale 1 is
# the World view. Europe covers western Iceland, North Cape, western
# Portugal, Cyprus and eastern Turkey at 375, 768 and 1280 px wide, in Edge
# and Firefox (searched and checked by tests/browser/test_map_page.py; 3.9
# would cut Cyprus off on a phone).
GEO_LON_RANGE = [-180, 180]
GEO_LAT_RANGE = [-58, 85]
VIEWS = {
    "world": {"scale": 1, "lon": 0, "lat": 13.5},
    "europe": {"scale": 3.5, "lon": 8, "lat": 52},
}


def view_relayout(name):
    """The relayout arguments that set the whole view for a preset."""
    view = VIEWS[name]
    return {
        "geo.projection.scale": view["scale"],
        "geo.center.lon": view["lon"],
        "geo.center.lat": view["lat"],
        "geo.projection.rotation.lon": view["lon"],
    }


# Plotly toolbar: keep download-as-PNG and reset. Remove "Share chart..."
# (sendChartToCloud), which uploads the chart to Plotly Cloud; the
# select/lasso tools (meaningless on a map); pan and zoom buttons (scroll
# zoom and drag do the same); and the Plotly logo.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "scrollZoom": True,
    "responsive": True,
    "modeBarButtonsToRemove": [
        "sendChartToCloud", "select2d", "lasso2d", "pan2d",
        "zoomInGeo", "zoomOutGeo", "hoverClosestGeo",
    ],
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


# --- data -> table ---------------------------------------------------------------

def tier_index(essentials):
    """0, 1, 2 for the tiers, 3 for no data (position in TIER_ORDER)."""
    if pd.isna(essentials):
        return 3
    return assign_tier(essentials, TIER_THRESHOLDS)


def flag_words(food, housing):
    """Flags on either category, in words; empty list if none."""
    words = []
    for flag in [food["flag"], housing["flag"]]:
        if pd.notna(flag):
            for letter in str(flag):
                word = FLAG_NAMES.get(letter, letter)
                if word not in words:
                    words.append(word)
    return words


def nearest_threshold(share):
    closest = None
    for threshold in TIER_THRESHOLDS:
        if closest is None or abs(share - threshold) < abs(share - closest):
            closest = threshold
    return closest


def build_hover(food, housing, name):
    """Hover text for one country-year, as HTML lines.

    Always: country and year, short tier, essentials with food and housing,
    the imputed-rent sub-line, one short source line. Only when they apply:
    flags, near a tier line, tourism, the COICOP version-gap footnote.
    """
    year = int(food["year"])
    lines = [f"<b>{name}</b>, {year}"]
    index = tier_index(food["essentials_share"])

    if index == 3:
        if food["frozen_back_data"]:
            lines.append("No data (1995-2009 values were estimated with")
            lines.append("a fixed spending structure, so they are not shown)")
        else:
            lines.append("No data")
    else:
        indent = "&nbsp;&nbsp;&nbsp;"
        lines.append(TIER_SHORT[index])
        lines.append(
            f"Essentials {food['essentials_share']:.1f}% "
            f"(food {food['share_pct']:.1f}%, housing {housing['share_pct']:.1f}%)"
        )
        if pd.notna(housing["imputed_rent_share_pct"]):
            lines.append(f"{indent}of which imputed rent {housing['imputed_rent_share_pct']:.1f}%")
        else:
            lines.append(f"{indent}imputed rent not published")
        lines.append(f"{food['source']}, COICOP {int(food['coicop_version'])}")

        flags = flag_words(food, housing)
        if flags:
            lines.append(", ".join(flags))
        if food["near_tier_boundary"]:
            line = nearest_threshold(food["essentials_share"])
            lines.append(f"Within {NEAR_BOUNDARY_MARGIN:g} pt of the {line}% tier line")
        if food["high_tourism"]:
            lines.append("Tourist spending lowers these shares")
        for row, label in [(food, "Food"), (housing, "Housing")]:
            if pd.notna(row["large_version_gap_pts"]):
                lines.append(
                    f"{label}: COICOP versions differ by up to "
                    f"{row['large_version_gap_pts']:.1f} pts (measured up to 2022)"
                )

    if food["iso3"] == "SRB":
        lines.append("Map: this shape includes Kosovo (not shown separately)")
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
        index = tier_index(food["essentials_share"])
        rows.append(
            {
                "iso3": iso3,
                "year": int(year),
                "tier": TIER_ORDER[index],
                "hover": build_hover(food, housing, ISO3_NAMES[iso3]),
            }
        )
    return pd.DataFrame(rows)


# --- figure --------------------------------------------------------------------

def country_traces(table, year):
    """The four country traces (one per tier) for one year. Every tier gets a
    trace, empty if no country is in it, so traces always line up by position."""
    in_year = table[table["year"] == year]
    traces = []
    for name in TIER_ORDER:
        rows = in_year[in_year["tier"] == name]
        hover = []
        for text in rows["hover"]:
            hover.append([text])
        traces.append(
            go.Choropleth(
                name=name,
                locations=list(rows["iso3"]),
                z=[0] * len(rows),
                customdata=hover,
            )
        )
    return traces


def legend_entry(name, color):
    """A permanent legend entry: an empty Scattergeo (no points, always listed)."""
    return go.Scattergeo(
        name=name,
        lon=[None],
        lat=[None],
        mode="markers",
        marker=dict(symbol="square", size=13, color=color, line=dict(width=0)),
        hoverinfo="skip",
        showlegend=True,
    )


def animation_args(duration):
    return dict(
        mode="immediate",
        fromcurrent=True,
        frame=dict(duration=duration, redraw=True),  # choropleths must redraw
        transition=dict(duration=0),
    )


def build_figure(table):
    years = sorted(table["year"].unique())

    # Traces 0-3: countries for the opening year, colours set once here.
    data = []
    for trace, color in zip(country_traces(table, MAP_DEFAULT_YEAR), tier_colors(LIGHT)):
        trace.update(
            colorscale=[[0, color], [1, color]],
            zmin=0,
            zmax=1,
            showscale=False,
            showlegend=False,
            hovertemplate="%{customdata[0]}<extra></extra>",
            marker_line_color=LIGHT["surface"],
            marker_line_width=0.6,
        )
        data.append(trace)
    # Traces 4-7: the legend, independent of the frames.
    for name, color in zip(TIER_ORDER, tier_colors(LIGHT)):
        data.append(legend_entry(name, color))

    # Frames: countries only (traces 0-3), no colours, no layout.
    frames = []
    for year in years:
        frames.append(go.Frame(name=str(year), data=country_traces(table, year), traces=[0, 1, 2, 3]))

    fig = go.Figure(data=data, frames=frames)
    world = VIEWS["world"]
    fig.update_geos(
        resolution=50,  # the default 110m map has no Malta
        projection_type="natural earth",
        projection_scale=world["scale"],
        projection_rotation_lon=world["lon"],
        center=dict(lon=world["lon"], lat=world["lat"]),
        lonaxis_range=GEO_LON_RANGE,
        lataxis_range=GEO_LAT_RANGE,
        showcountries=True,
        countrycolor=LIGHT["surface"],
        showland=True,
        landcolor=LIGHT["land"],
        showcoastlines=False,
        showocean=False,
        showlakes=False,
        showframe=False,
        bgcolor=LIGHT["surface"],
    )

    steps = []
    for year in years:
        steps.append(dict(label=str(year), method="animate", args=[[str(year)], animation_args(0)]))
    fig.update_layout(
        paper_bgcolor=LIGHT["surface"],
        plot_bgcolor=LIGHT["surface"],
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=LIGHT["text"]),
        margin=dict(l=10, r=10, t=10, b=10),
        height=620,
        # Must stay "pan": with dragmode off, Plotly also turns scroll zoom off.
        # Dragging at World scale is blocked by the page script instead.
        dragmode="pan",
        legend=dict(
            title=dict(text=LEGEND_TITLE),
            orientation="v", x=0.01, y=0.06, xanchor="left", yanchor="bottom",
            bgcolor=LIGHT["legend_bg"],
            itemclick=False,        # clicking would only hide the legend entry
            itemdoubleclick=False,
        ),
        hoverlabel=dict(bgcolor=LIGHT["control_bg"], font_size=13, align="left"),
        sliders=[dict(
            active=years.index(MAP_DEFAULT_YEAR),
            currentvalue=dict(prefix="Year: "),
            pad=dict(t=40, b=10),
            x=0, len=1, xanchor="left", y=0, yanchor="top",
            steps=steps,
        )],
        # No Plotly play buttons: their animation promise rejects (uncaught)
        # when Pause interrupts Play. The page has its own Play / Pause.
    )
    return fig


def check_frames(fig, years):
    """Stop the build if any frame could put a colour on the wrong tier,
    drop a legend entry, or change the view.

    Plotly matches traces between frames by POSITION, so every frame must
    carry the four tiers in the same order; frames must carry no colours
    (the theme sets them once) and no layout (the view must survive Play).
    """
    if [frame.name for frame in fig.frames] != [str(year) for year in years]:
        raise ValueError("Frames do not match the years")
    for frame in fig.frames:
        if list(frame.traces) != [0, 1, 2, 3]:
            raise ValueError(f"Frame {frame.name} targets traces {frame.traces}")
        if [trace.name for trace in frame.data] != TIER_ORDER:
            raise ValueError(f"Frame {frame.name}: tier traces out of order")
        for trace in frame.data:
            if trace.colorscale is not None:
                raise ValueError(f"Frame {frame.name}: trace carries its own colours")
        if frame.layout and frame.layout.to_plotly_json():
            raise ValueError(f"Frame {frame.name} carries layout, which would override the view")
    names = [trace.name for trace in fig.data]
    if names != TIER_ORDER + TIER_ORDER:
        raise ValueError(f"Unexpected base traces: {names}")
    for trace, color in zip(fig.data[:4], tier_colors(LIGHT)):
        if trace.colorscale[0][1] != color:
            raise ValueError(f"Trace {trace.name} has colour {trace.colorscale[0][1]}")
    for trace in fig.data[4:]:
        if trace.type != "scattergeo" or not trace.showlegend:
            raise ValueError(f"Legend entry {trace.name} is not a permanent legend trace")
    print(f"Frame check: {len(fig.frames)} frames, 4 tiers in order, no colours or layout in "
          f"frames; 4 permanent legend entries.")


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
        if "<b>Serbia</b>" not in hover:
            raise ValueError(f"{year}: unexpected country name in Serbia's hover")
    print(f"Kosovo check: XKX in none of {len(fig.frames)} frames; Serbia appears once per "
          f"frame with its own tier and hover.")


# --- page ----------------------------------------------------------------------

def theme_payload():
    """What the page script needs to recolour the map for a theme."""
    payload = {}
    for mode, theme in THEMES.items():
        scales = []
        for color in tier_colors(theme):
            scales.append([[0, color], [1, color]])
        payload[mode] = {
            "scales": scales,
            "legendColors": tier_colors(theme),
            "border": theme["surface"],
            "layout": {
                "paper_bgcolor": theme["surface"],
                "plot_bgcolor": theme["surface"],
                "font.color": theme["text"],
                "geo.bgcolor": theme["surface"],
                "geo.landcolor": theme["land"],
                "geo.countrycolor": theme["surface"],
                "legend.bgcolor": theme["legend_bg"],
                "legend.font.color": theme["text"],
                "hoverlabel.bgcolor": theme["control_bg"],
                "hoverlabel.font.color": theme["text"],
                "hoverlabel.bordercolor": theme["border"],
                "sliders[0].bgcolor": theme["control_bg"],
                "sliders[0].bordercolor": theme["border"],
                "sliders[0].font.color": theme["text"],
                "sliders[0].currentvalue.font.color": theme["text"],
            },
        }
    return payload


# Runs first, in <head>: applies the stored or system theme before the page
# is painted, so there is no flash of the wrong theme.
EARLY_THEME_SCRIPT = """(function () {
  var choice = "system";
  try { choice = localStorage.getItem("fhs-theme") || "system"; } catch (e) {}
  var dark = choice === "dark" ||
    (choice === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme-choice", choice);
})();"""


PAGE_SCRIPT = """(function () {
  var map = document.getElementById("map");
  var note = document.getElementById("year-note");
  var themes = __THEMES__;
  var views = __VIEWS__;
  var covidNotes = __COVID__;
  var GEO_LON = __GEO_LON__, GEO_LAT = __GEO_LAT__;
  var darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  var STORAGE_KEY = "fhs-theme";

  // ---- theme ------------------------------------------------------------
  function storedChoice() {
    try { return localStorage.getItem(STORAGE_KEY) || "system"; } catch (e) { return "system"; }
  }
  function storeChoice(choice) {
    try { localStorage.setItem(STORAGE_KEY, choice); } catch (e) {}
  }
  function modeFor(choice) {
    if (choice === "light" || choice === "dark") { return choice; }
    return darkQuery.matches ? "dark" : "light";
  }
  function applyTheme(choice) {
    var mode = modeFor(choice);
    document.documentElement.setAttribute("data-theme", mode);
    document.documentElement.setAttribute("data-theme-choice", choice);
    document.querySelectorAll("[data-theme-button]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.themeButton === choice));
    });
    var theme = themes[mode];
    // Frames carry no colours, so this one change holds for every year.
    Plotly.restyle(map, { colorscale: theme.scales, "marker.line.color": theme.border }, [0, 1, 2, 3]);
    Plotly.restyle(map, { "marker.color": theme.legendColors }, [4, 5, 6, 7]);
    Plotly.relayout(map, theme.layout);
  }

  // ---- views: presets and clamped zoom ------------------------------------
  function relayoutFor(name) {
    var v = views[name];
    return {
      "geo.projection.scale": v.scale, "geo.center.lon": v.lon,
      "geo.center.lat": v.lat, "geo.projection.rotation.lon": v.lon
    };
  }
  function currentView() {
    var geo = map.layout.geo || {};
    var projection = geo.projection || {};
    var center = geo.center || {};
    return {
      scale: projection.scale == null ? 1 : projection.scale,
      lon: center.lon == null ? views.world.lon : center.lon,
      lat: center.lat == null ? views.world.lat : center.lat,
      rotation: (projection.rotation || {}).lon == null ? 0 : projection.rotation.lon
    };
  }
  function limit(value, low, high) { return Math.min(Math.max(value, low), high); }
  // The view that is allowed: never zoomed out beyond World; at World scale
  // centred and not draggable; zoomed in, the centre stays far enough from
  // the edges that the map cannot leave the frame (and is never rotated
  // beyond panning: rotation follows the centre longitude).
  function clampedView(view) {
    var scale = Math.max(view.scale, 1);
    if (scale <= 1.0001) {
      return { scale: 1, lon: views.world.lon, lat: views.world.lat };
    }
    var halfLon = (GEO_LON[1] - GEO_LON[0]) / 2 / scale;
    var halfLat = (GEO_LAT[1] - GEO_LAT[0]) / 2 / scale;
    return {
      scale: scale,
      lon: limit(view.lon, GEO_LON[0] + halfLon, GEO_LON[1] - halfLon),
      lat: limit(view.lat, GEO_LAT[0] + halfLat, GEO_LAT[1] - halfLat)
    };
  }
  var clamping = false;
  function enforceLimits() {
    var now = currentView();
    var allowed = clampedView(now);
    var off = Math.abs(now.scale - allowed.scale) > 1e-6 || Math.abs(now.lon - allowed.lon) > 1e-6 ||
              Math.abs(now.lat - allowed.lat) > 1e-6 || Math.abs(now.rotation - allowed.lon) > 1e-6;
    if (off) {
      clamping = true;
      Plotly.relayout(map, {
        "geo.projection.scale": allowed.scale, "geo.center.lon": allowed.lon,
        "geo.center.lat": allowed.lat, "geo.projection.rotation.lon": allowed.lon
      }).then(function () { clamping = false; markPreset(); },
              function () { clamping = false; });
    } else {
      markPreset();
    }
  }
  function markPreset() {
    var now = currentView();
    document.querySelectorAll("[data-view]").forEach(function (button) {
      var v = views[button.dataset.view];
      var same = Math.abs(now.scale - v.scale) < 1e-3 && Math.abs(now.lon - v.lon) < 1e-3 &&
                 Math.abs(now.lat - v.lat) < 1e-3;
      button.setAttribute("aria-pressed", String(same));
    });
  }
  map.on("plotly_relayout", function () {
    if (!clamping) { window.requestAnimationFrame(enforceLimits); }
  });
  // At World scale the map cannot be dragged: stop the press before it
  // reaches Plotly's drag handler. (Plotly's own "no drag" setting would
  // also switch scroll zoom off.) Scroll zoom and hover are not affected.
  function blockDragAtWorld(event) {
    var onMap = event.target && event.target.closest && event.target.closest("#map .geo");
    if (onMap && currentView().scale <= 1.0001) { event.stopPropagation(); }
  }
  ["mousedown", "pointerdown", "touchstart"].forEach(function (type) {
    map.addEventListener(type, blockDragAtWorld, true);
  });

  // ---- years: note, Play / Pause -------------------------------------------
  var years = __YEARS__;
  var currentYear = __DEFAULT_YEAR__;
  var playButton = document.querySelector("[data-play]");
  function showYear(year) {
    currentYear = Number(year);
    note.textContent = covidNotes[String(year)] || "";
  }
  map.on("plotly_sliderchange", function (event) { showYear(event.step.label); });
  map.on("plotly_animatingframe", function (event) { showYear(event.name); });
  function setPlaying(playing) {
    playButton.setAttribute("aria-pressed", String(playing));
    playButton.textContent = playing ? "Pause" : "Play";
  }
  function play() {
    // From the year after the current one; from the start if at the end.
    var start = years.indexOf(currentYear) + 1;
    if (start <= 0 || start >= years.length) { start = 0; }
    var names = years.slice(start).map(String);
    setPlaying(true);
    // Plotly rejects this promise when the animation is interrupted (Pause,
    // or the slider): expected, so it is caught rather than reported.
    Plotly.animate(map, names, {
      mode: "immediate", frame: { duration: 700, redraw: true }, transition: { duration: 0 }
    }).then(function () { setPlaying(false); }, function () { setPlaying(false); });
  }
  function pause() {
    Plotly.animate(map, [null], {
      mode: "immediate", frame: { duration: 0, redraw: false }, transition: { duration: 0 }
    }).catch(function () {});
    setPlaying(false);
  }
  playButton.addEventListener("click", function () {
    if (playButton.getAttribute("aria-pressed") === "true") { pause(); } else { play(); }
  });

  // ---- wiring -------------------------------------------------------------
  document.querySelectorAll("[data-theme-button]").forEach(function (button) {
    button.addEventListener("click", function () {
      storeChoice(button.dataset.themeButton);
      applyTheme(button.dataset.themeButton);
    });
  });
  darkQuery.addEventListener("change", function () {
    if (storedChoice() === "system") { applyTheme("system"); }
  });
  document.querySelectorAll("[data-view]").forEach(function (button) {
    button.addEventListener("click", function () {
      clamping = true;
      Plotly.relayout(map, relayoutFor(button.dataset.view)).then(
        function () { clamping = false; markPreset(); },
        function () { clamping = false; });
    });
  });

  // Called by Plotly once the map is drawn (post_script); whichever finishes
  // last (Plotly drawing, or this script) starts it.
  window.initMap = function () {
    showYear(__DEFAULT_YEAR__);
    applyTheme(storedChoice());
    markPreset();
  };
  if (window.mapDrawn) { window.initMap(); }
})();"""


def page_script():
    replacements = {
        "__THEMES__": json.dumps(theme_payload()),
        "__VIEWS__": json.dumps(VIEWS),
        "__COVID__": json.dumps({str(year): COVID_NOTE.format(year=year) for year in COVID_YEARS}),
        "__GEO_LON__": json.dumps(GEO_LON_RANGE),
        "__GEO_LAT__": json.dumps(GEO_LAT_RANGE),
        "__DEFAULT_YEAR__": str(MAP_DEFAULT_YEAR),
        "__YEARS__": json.dumps(list(range(FIRST_YEAR, MAP_LAST_YEAR + 1))),
    }
    script = PAGE_SCRIPT
    for placeholder, value in replacements.items():
        script = script.replace(placeholder, value)
    return script


def page_html(fig, table):
    """The page: header with theme toggle, caption, view buttons, map, notes."""
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
    light, dark = THEMES["light"], THEMES["dark"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Food & Housing Spending Share</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<script>{EARLY_THEME_SCRIPT}</script>
<style>
  :root {{ --surface: {light['surface']}; --text: {light['text']}; --text-2: {light['text_2']};
          --border: {light['border']}; --control: {light['control_bg']}; --accent: {light['tiers'][1]};
          color-scheme: light; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{ --surface: {dark['surface']}; --text: {dark['text']};
          --text-2: {dark['text_2']}; --border: {dark['border']}; --control: {dark['control_bg']};
          --accent: {dark['tiers'][1]}; color-scheme: dark; }}
  }}
  :root[data-theme="dark"] {{ --surface: {dark['surface']}; --text: {dark['text']};
          --text-2: {dark['text_2']}; --border: {dark['border']}; --control: {dark['control_bg']};
          --accent: {dark['tiers'][1]}; color-scheme: dark; }}
  body {{ margin: 0; background: var(--surface); color: var(--text);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
  header {{ display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: flex-start;
           justify-content: space-between; }}
  h1 {{ font-size: 1.5rem; margin: 0.25rem 0; flex: 1 1 20rem; }}
  .lede, .caption {{ color: var(--text-2); margin: 0 0 0.75rem; }}
  .caption {{ font-size: 0.9rem; }}
  .segmented {{ display: inline-flex; border: 1px solid var(--border); border-radius: 6px;
               overflow: hidden; }}
  .segmented button {{ font: inherit; font-size: 0.85rem; padding: 4px 10px; border: 0;
                      background: var(--control); color: var(--text); cursor: pointer; }}
  .segmented button + button {{ border-left: 1px solid var(--border); }}
  .segmented button[aria-pressed="true"] {{ background: var(--accent); color: #ffffff; }}
  .segmented button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -2px; }}
  .map-tools {{ display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
               margin: 0.25rem 0; }}
  .year-note {{ min-height: 1.4em; font-size: 0.9rem; color: var(--text-2); margin: 0; flex: 1 1 16rem; }}
  ul {{ color: var(--text-2); font-size: 0.9rem; padding-left: 1.2rem; }}
  a {{ color: inherit; }}
</style>
</head>
<body>
<main>
<header>
<h1>How much of household spending goes to food and housing</h1>
<div class="segmented" role="group" aria-label="Colour theme">
  <button type="button" data-theme-button="system" aria-pressed="true">System</button>
  <button type="button" data-theme-button="light" aria-pressed="false">Light</button>
  <button type="button" data-theme-button="dark" aria-pressed="false">Dark</button>
</div>
</header>
<p class="lede">Food and housing &amp; utilities as a share of household consumption spending,
{FIRST_YEAR}-{MAP_LAST_YEAR}, OECD and European countries.
{MAP_DEFAULT_YEAR}: {n_data} of {len(latest)} mapped countries have data.</p>
<p class="caption"><strong>What the tiers measure:</strong> the essentials share, i.e. spending on
food &amp; non-alcoholic beverages plus housing &amp; utilities (incl. imputed rent), as a % of
total household consumption spending. Fixed thresholds, the same for every country and year:
<strong>lower</strong> below {LOW}%, <strong>moderate</strong> {LOW}% to {HIGH}%,
<strong>higher</strong> {HIGH}% or more. A share of spending, not of income.</p>
<div class="map-tools">
  <div class="segmented" role="group" aria-label="Map view">
    <button type="button" data-view="world" aria-pressed="true">World</button>
    <button type="button" data-view="europe" aria-pressed="false">Europe</button>
  </div>
  <div class="segmented" role="group" aria-label="Years">
    <button type="button" data-play aria-pressed="false">Play</button>
  </div>
  <p class="year-note" id="year-note" aria-live="polite"></p>
</div>
{figure_html}
<ul>
  <li>Official statistics from Eurostat and the OECD.
      <a href="shares.csv" download>Download the data (CSV)</a>.</li>
  <li>Scroll to zoom; drag to move once zoomed in. World and Europe reset the view.</li>
  <li>Not an affordability or overburden measure: it compares spending shares, not costs
      against income.</li>
  <li>Housing &amp; utilities includes imputed rent (what owner-occupiers would pay to rent
      their own home), which countries estimate in different ways.</li>
  <li>Grey: in scope but no data for that year. Plain land: outside this project's scope.</li>
  <li>Kosovo: the base map draws Kosovo's territory as part of Serbia, so that area shows
      Serbia's colour and data. Kosovo's own figures (2008-2017) are in the data download
      but cannot be shown on the map.</li>
  <li>Very small countries (Malta, Luxembourg, Cyprus) are only a few pixels wide; zoom in
      and hover to read them.</li>
  <li>{MAP_LAST_YEAR + 1} is not shown: too few countries had published it.</li>
</ul>
</main>
<script>{page_script()}</script>
</body>
</html>
"""


# --- CSP -----------------------------------------------------------------------

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


# --- static images (README) ----------------------------------------------------

def save_png(fig, path, view_name):
    """Static image of the opening year, light theme, no controls."""
    static = go.Figure(data=fig.data, layout=fig.layout)
    # Assign (not update_layout): update_layout merges and would keep them.
    static.layout.sliders = ()
    view = VIEWS[view_name]
    static.update_layout(width=1200, height=620)
    static.update_geos(
        projection_scale=view["scale"],
        projection_rotation_lon=view["lon"],
        center=dict(lon=view["lon"], lat=view["lat"]),
    )
    static.write_image(path, scale=2)


def main():
    table = country_year_table()
    years = sorted(table["year"].unique())
    fig = build_figure(table)
    check_frames(fig, years)
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

    for suffix, view_name in [("", "world"), ("_europe", "europe")]:
        png_path = IMAGES_DIR / f"map_{MAP_DEFAULT_YEAR}{suffix}.png"
        save_png(fig, png_path, view_name)
        print(f"Saved {png_path}")

    latest = table[table["year"] == MAP_DEFAULT_YEAR]
    print(f"\n{MAP_DEFAULT_YEAR} on the map:")
    print(latest["tier"].value_counts().reindex(TIER_ORDER, fill_value=0).to_string())


if __name__ == "__main__":
    main()
