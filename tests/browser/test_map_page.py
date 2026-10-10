"""Browser regression tests for site/index.html, in Edge and Firefox.

Serves site/ locally with the same response headers as
deploy/food-housing.caddy, then checks, in each browser:

  csp        0 CSP violations, 0 console errors, 0 failed requests across all
             interactions; an unhashed extra script IS blocked (control);
             the CSP <meta> is the first element in <head>
  legend     4 legend entries in every one of the 30 years
  views      World and Europe set the whole view; Europe shows Iceland,
             Cyprus, eastern Turkey, North Cape and western Portugal
  clamp      scroll out 50x stays at World; no dragging at World scale;
             zoomed into the Balkans, Play and the slider keep the view;
             dragging stays inside the bounds; Europe / World reset
  layout     view buttons, Play and theme toggle never overlap the Plotly
             toolbar at 375, 768 and 1280 px wide; map height is
             clamp(360px, 75vw, 620px); World and Europe framing at each width;
             the legend covers no in-scope country (above the map below 1000 px)
  theme      System (light and dark OS), Light, Dark: page, land, tiers
             and legend use that theme's colours after a year change, Play,
             Europe and World; the choice survives a reload
  hover      the live tooltip for Germany matches the page data

Run from the project root, after src/build_map.py:
    uv run --with playwright python tests/browser/test_map_page.py
(Firefox needs Playwright's build once: uv run --with playwright playwright install firefox)
"""

import http.server
import json
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "src"))
from build_map import THEMES, TIER_ORDER, VIEWS, tier_colors  # noqa: E402

PORT = 8770
BASE = f"http://127.0.0.1:{PORT}"
CADDY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'",
}
# Places that must be inside the Europe view (lon, lat).
EUROPE_MUST_SHOW = {
    "western Iceland": (-24.3, 65.5),
    "North Cape": (25.8, 71.1),
    "western Portugal": (-9.4, 38.8),
    "Cyprus": (33.0, 34.9),
    "eastern Turkey": (44.5, 39.5),
}
# Places that must be inside the World view: the corners of the project's scope.
WORLD_MUST_SHOW = {
    "western Alaska": (-165.0, 64.0),
    "southern Chile": (-71.0, -52.0),
    "Japan": (140.0, 36.0),
    "New Zealand": (174.0, -41.0),
    "North Cape": (25.8, 71.1),
}
# In-scope countries near the map edges that a legend could cover.
LEGEND_MUST_NOT_COVER = {
    "southern Chile": (-71.0, -48.0),
    "northern Chile": (-70.0, -22.0),
    "Colombia": (-74.0, 4.0),
    "Mexico": (-102.0, 23.0),
    "Australia": (134.0, -25.0),
    "New Zealand": (172.0, -42.0),
}
BALKANS = (20.5, 43.5)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


# --- local server with the deployed headers ------------------------------------

TAMPER_DIR = Path(tempfile.mkdtemp())


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def end_headers(self):
        for name, value in CADDY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def translate_path(self, path):
        if path.startswith("/tampered.html"):
            return str(TAMPER_DIR / "tampered.html")
        return super().translate_path(path)

    def log_message(self, *args):
        pass


def start_server():
    page = (SITE / "index.html").read_text(encoding="utf-8")
    tampered = page.replace("</body>", '<script>console.log("not in the policy")</script>\n</body>')
    (TAMPER_DIR / "tampered.html").write_text(tampered, encoding="utf-8", newline="\n")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# --- helpers that read the page -------------------------------------------------

COLLECT_VIOLATIONS = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', function (e) {
  window.__csp.push(e.effectiveDirective + ' blocked ' + (e.blockedURI || 'inline'));
});
"""


def hex_to_rgb(color):
    color = color.lstrip("#")
    return f"rgb({int(color[0:2], 16)}, {int(color[2:4], 16)}, {int(color[4:6], 16)})"


def view(page):
    return page.evaluate("""() => { const g = document.getElementById('map').layout.geo || {};
        const p = g.projection || {}, c = g.center || {};
        return {scale: p.scale == null ? 1 : p.scale, lon: c.lon == null ? 0 : c.lon,
                lat: c.lat == null ? 13.5 : c.lat,
                rotation: (p.rotation || {}).lon == null ? 0 : p.rotation.lon,
                dragmode: document.getElementById('map').layout.dragmode}; }""")


def same_view(a, b, tolerance=1e-3):
    return all(abs(a[key] - b[key]) < tolerance for key in ("scale", "lon", "lat"))


def preset(name):
    v = VIEWS[name]
    return {"scale": v["scale"], "lon": v["lon"], "lat": v["lat"]}


def screen_point(page, lon, lat):
    """Screen coordinates of a lon/lat, and whether it is inside the map frame."""
    return page.evaluate("""([lon, lat]) => {
        // Projection coordinates share the clip rectangle's coordinate space.
        // Read the clip's attributes (Firefox returns an empty getBBox for
        // it); the framework's screen box starts at the clip's x / y.
        const sp = document.getElementById('map')._fullLayout.geo._subplot;
        const [x, y] = sp.projection([lon, lat]);
        const c = sp.clipRect.node();
        const cx = +c.getAttribute('x'), cy = +c.getAttribute('y');
        const cw = +c.getAttribute('width'), ch = +c.getAttribute('height');
        const frame = sp.framework.node().getBoundingClientRect();
        const inside = x >= cx && x <= cx + cw && y >= cy && y <= cy + ch;
        return {x: frame.left - cx + x, y: frame.top - cy + y, inside};
    }""", [lon, lat])


def settle(page, ms=700):
    page.wait_for_timeout(ms)


def wait_for_map(page):
    page.wait_for_selector("#map .choroplethlocation", timeout=30000)
    page.wait_for_function("window.mapDrawn === true", timeout=30000)
    settle(page, 800)


def click_view(page, name):
    page.locator(f'[data-view="{name}"]').click()
    settle(page)


def go_to_year_with_slider(page, year):
    """Click the slider rail at the position of `year` (a real user action)."""
    rail = page.locator(".slider-rail-rect").bounding_box()
    fraction = (year - 1995) / (2024 - 1995)
    page.mouse.click(rail["x"] + 8 + fraction * (rail["width"] - 16), rail["y"] + rail["height"] / 2)
    settle(page, 900)


def current_year(page):
    return page.evaluate("""() => { const s = document.getElementById('map')._fullLayout.sliders[0];
        return Number(s.steps[s.active].label); }""")


def press_play(page, seconds):
    """Play for `seconds`, then Pause (the same button)."""
    page.locator("[data-play]").click()
    page.wait_for_timeout(int(seconds * 1000))
    page.locator("[data-play]").click()
    settle(page, 900)


def theme_colors(page):
    """What the page is actually painting right now."""
    return page.evaluate("""() => {
        const fills = new Set();
        document.querySelectorAll('#map .choroplethlocation').forEach(e => fills.add(getComputedStyle(e).fill));
        const legend = [];
        document.querySelectorAll('#map .legend .traces .legendpoints path').forEach(e => legend.push(getComputedStyle(e).fill));
        const land = document.querySelector('#map .geo .layer.land path');
        return {fills: Array.from(fills), legend,
                land: land ? getComputedStyle(land).fill : null,
                body: getComputedStyle(document.body).backgroundColor,
                dataTheme: document.documentElement.getAttribute('data-theme')}; }""")


def colors_match(page, mode):
    theme = THEMES[mode]
    painted = theme_colors(page)
    allowed = {hex_to_rgb(c) for c in tier_colors(theme)}
    problems = []
    if painted["dataTheme"] != mode:
        problems.append(f"data-theme={painted['dataTheme']}")
    if painted["body"] != hex_to_rgb(theme["surface"]):
        problems.append(f"body {painted['body']}")
    if painted["land"] != hex_to_rgb(theme["land"]):
        problems.append(f"land {painted['land']}")
    stray = [f for f in painted["fills"] if f not in allowed]
    if stray:
        problems.append(f"country fills not in the {mode} ramp: {stray}")
    if painted["legend"] != [hex_to_rgb(c) for c in tier_colors(theme)]:
        problems.append(f"legend {painted['legend']}")
    return problems


def legend_entries(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#map .legend .traces .legendtext'))
        .map(e => e.textContent)""")


# --- the tests ------------------------------------------------------------------

def test_csp_and_console(browser, scheme):
    problems = []
    context = browser.new_context(color_scheme=scheme, accept_downloads=True,
                                  viewport={"width": 1280, "height": 1000})
    context.add_init_script(COLLECT_VIOLATIONS)
    page = context.new_page()
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text[:150]}")
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {str(e)[:150]}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    page.goto(BASE + "/index.html")
    wait_for_map(page)
    first = page.evaluate("document.head.firstElementChild.outerHTML.slice(0, 50)")
    check(f"[{scheme}] CSP <meta> is first in <head>", first.startswith('<meta http-equiv="Content-Security-Policy"'))
    # Everything a visitor can do.
    box = page.locator("#map").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -300)
    settle(page)
    click_view(page, "europe")
    click_view(page, "world")
    go_to_year_with_slider(page, 2010)
    press_play(page, 2)
    page.locator("[data-play]").click()          # Play, then move the slider while playing
    page.wait_for_timeout(800)
    go_to_year_with_slider(page, 2015)
    page.locator("[data-play]").click() if page.locator("[data-play]").get_attribute("aria-pressed") == "true" else None
    settle(page)
    for button in ["dark", "light", "system"]:
        page.locator(f'[data-theme-button="{button}"]').click()
        settle(page, 300)
    page.locator("#map").hover()
    with page.expect_download(timeout=20000):
        page.locator('[data-title="Download plot as a PNG"]').click()
    with page.expect_download(timeout=20000):
        page.get_by_text("Download the data (CSV)").click()
    settle(page)
    violations = page.evaluate("window.__csp")
    check(f"[{scheme}] 0 CSP violations", not violations, "; ".join(violations))
    check(f"[{scheme}] 0 console errors / failed requests", not problems, "; ".join(problems))
    control = context.new_page()
    control.goto(BASE + "/tampered.html")
    control.wait_for_timeout(2500)
    blocked = control.evaluate("window.__csp")
    check(f"[{scheme}] negative control: unhashed script is blocked", blocked, "; ".join(blocked))
    toolbar = page.eval_on_selector_all(".modebar-btn", "els => els.map(e => e.getAttribute('data-title'))")
    check(f"[{scheme}] toolbar is PNG download + reset only", toolbar == ["Download plot as a PNG", "Reset"], str(toolbar))
    context.close()


def test_legend_every_year(page):
    missing = []
    for year in range(1995, 2025):
        page.evaluate("(y) => Plotly.animate('map', [String(y)], {mode: 'immediate', frame: {duration: 0, redraw: true}, transition: {duration: 0}})", year)
        page.wait_for_timeout(150)
        entries = legend_entries(page)
        if entries != TIER_ORDER:
            missing.append(f"{year}: {entries}")
    check("legend has the 4 entries in all 30 years", not missing, "; ".join(missing[:3]))
    go_to_year_with_slider(page, 2024)


def test_views(page):
    click_view(page, "europe")
    check("Europe sets the whole view (scale, centre)", same_view(view(page), preset("europe")), str(view(page)))
    outside = []
    for place, (lon, lat) in EUROPE_MUST_SHOW.items():
        if not screen_point(page, lon, lat)["inside"]:
            outside.append(place)
    check("Europe view shows Iceland, North Cape, Portugal, Cyprus, eastern Turkey", not outside, f"outside: {outside}")
    click_view(page, "world")
    check("World resets the whole view", same_view(view(page), preset("world")) and abs(view(page)["rotation"]) < 1e-3,
          str(view(page)))
    go_to_year_with_slider(page, 2024)
    page.locator("[data-play]").click()
    page.wait_for_timeout(2200)
    year = current_year(page)
    page.locator("[data-play]").click()
    settle(page)
    check("Play at the last year restarts from 1995", 1995 <= year <= 1999, f"year after 2.2 s: {year}")
    go_to_year_with_slider(page, 2024)


def test_clamp(page):
    click_view(page, "world")
    box = page.locator("#map .geo").first.bounding_box()
    middle = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.move(*middle)
    for _ in range(50):
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(20)
    settle(page, 1000)
    check("scroll out 50x: stays at World", same_view(view(page), preset("world")), str(view(page)))

    before = view(page)
    page.mouse.move(*middle)
    page.mouse.down()
    page.mouse.move(middle[0] + 250, middle[1] + 100, steps=8)
    page.mouse.up()
    settle(page)
    check("drag at World scale does nothing", same_view(view(page), before), str(view(page)))

    point = screen_point(page, *BALKANS)
    page.mouse.move(point["x"], point["y"])
    for _ in range(6):
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(120)
    settle(page, 1000)
    zoomed = view(page)
    near = abs(zoomed["lon"] - BALKANS[0]) < 25 and abs(zoomed["lat"] - BALKANS[1]) < 20
    check("zoom into the Balkans", zoomed["scale"] > 3 and near, str(zoomed))

    press_play(page, 2.5)
    check("Play keeps the zoomed view", same_view(view(page), zoomed), str(view(page)))
    go_to_year_with_slider(page, 2001)
    check("slider scrub keeps the zoomed view", same_view(view(page), zoomed) and current_year(page) == 2001,
          f"{view(page)} year {current_year(page)}")

    # Push against the bounds with many ordinary drags, all inside the
    # window (Firefox delivers no mouse events once the pointer leaves it).
    box = page.locator("#map .geo").first.bounding_box()
    start = (box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.3)
    start_sampler(page)
    for _ in range(12):
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(start[0] + box["width"] * 0.4, start[1] + box["height"] * 0.4, steps=8)
        page.mouse.up()
        page.wait_for_timeout(150)
    settle(page, 1000)
    sampled = stop_sampler(page)
    after = view(page)
    check("zoomed: dragging pans but never leaves the world or rotates (every frame)",
          not sampled["violations"] and after["lon"] != zoomed["lon"] and abs(after["rotation"]) < 1e-9,
          f"{sampled['frames']} frames, violations {sampled['violations'][:3]}, view {after}")

    click_view(page, "europe")
    check("Europe after zoom + drag: exact preset", same_view(view(page), preset("europe")), str(view(page)))
    click_view(page, "world")
    check("World after that: exact preset", same_view(view(page), preset("world")), str(view(page)))
    before = view(page)
    page.mouse.move(*middle)
    page.mouse.down()
    page.mouse.move(middle[0] - 300, middle[1] - 120, steps=8)
    page.mouse.up()
    settle(page)
    check("drag at World scale still does nothing afterwards", same_view(view(page), before), str(view(page)))
    go_to_year_with_slider(page, 2024)


# --- per-frame view checks (independent of the page's own limit code) --------
#
# On every animation frame, inspect the projection that is actually drawn:
#   - scale never below World, rotation always [0, 0, 0];
#   - no wrap: along horizontal scans the on-map longitudes only increase;
#   - points just inside the frame's edges are on the map (they convert to
#     lon/lat and back to the same pixel) and inside +-180 / 85 N / 58 S;
#     off-map points are allowed only along an axis where the map is narrower
#     than the frame, and then the map must be centred along that axis.
SAMPLER = """
window.__view = {frames: 0, minScale: Infinity, violations: [], running: false};
window.__viewCheck = function () {
  const gd = document.getElementById('map');
  const sp = gd && gd._fullLayout && gd._fullLayout.geo && gd._fullLayout.geo._subplot;
  if (!sp || !sp.projection) return;
  const p = sp.projection, c = sp.clipRect.node(), v = window.__view;
  const X = +c.getAttribute('x'), Y = +c.getAttribute('y'), W = +c.getAttribute('width'), H = +c.getAttribute('height');
  const scale = p.scale() / sp.fitScale, r = p.rotate();
  v.frames++; v.minScale = Math.min(v.minScale, scale);
  const add = (text) => { if (v.violations.length < 20) v.violations.push(text); };
  if (scale < 1 - 1e-6) add('scale ' + scale.toFixed(4) + ' below World');
  if (Math.abs(r[0]) > 1e-9 || Math.abs(r[1]) > 1e-9 || Math.abs(r[2]) > 1e-9) add('rotated ' + r.map(x => x.toFixed(3)));
  const onMap = (x, y) => {
    const ll = p.invert([x, y]);
    if (!ll || !isFinite(ll[0]) || !isFinite(ll[1])) return false;
    const back = p(ll);
    if (!back || Math.abs(back[0] - x) > 1.5 || Math.abs(back[1] - y) > 1.5) return false;
    return ll[0] >= -180 && ll[0] <= 180 && ll[1] >= -58.01 && ll[1] <= 85.01;
  };
  const inset = 0.5, n = 24;
  let offSides = false, offTopBottom = false, offCorner = false;
  for (let i = 0; i <= n; i++) {
    const fx = X + inset + (W - 2 * inset) * i / n, fy = Y + inset + (H - 2 * inset) * i / n;
    const middle = i >= n * 0.25 && i <= n * 0.75;
    for (const [x, y, side] of [[fx, Y + inset, 'tb'], [fx, Y + H - inset, 'tb'], [X + inset, fy, 'lr'], [X + W - inset, fy, 'lr']]) {
      if (onMap(x, y)) continue;
      if (!middle) offCorner = true; else if (side === 'lr') offSides = true; else offTopBottom = true;
    }
  }
  const xL = p([-179.999, 0])[0], xR = p([179.999, 0])[0], yN = p([0, 85])[1], yS = p([0, -58])[1];
  const hCentred = Math.abs((xL + xR) / 2 - (X + W / 2)) < 1.5;
  const vCentred = Math.abs((yN + yS) / 2 - (Y + H / 2)) < 1.5;
  if (offSides && !hCentred) add('space beyond +-180 while not centred (scale ' + scale.toFixed(2) + ')');
  if (offTopBottom && !vCentred) add('space beyond 85N/58S while not centred (scale ' + scale.toFixed(2) + ')');
  if (offCorner && !hCentred && !vCentred) add('corner off the map, neither axis centred (scale ' + scale.toFixed(2) + ')');
  for (let row = 1; row <= 5; row++) {
    const y = Y + H * row / 6; let previous = null;
    for (let i = 0; i <= 40; i++) {
      const x = X + W * i / 40; if (!onMap(x, y)) continue;
      const lon = p.invert([x, y])[0];
      if (previous !== null && lon < previous - 1e-6) { add('wrap: longitude jumps back at row ' + row); break; }
      previous = lon;
    }
  }
};
window.__viewLoop = function () { if (!window.__view.running) return; window.__viewCheck(); requestAnimationFrame(window.__viewLoop); };
"""


def start_sampler(page):
    page.evaluate("() => { if (!window.__viewLoop) {" + SAMPLER + "} }")
    page.evaluate("() => { window.__view = {frames: 0, minScale: Infinity, violations: [], running: true}; requestAnimationFrame(window.__viewLoop); }")


def stop_sampler(page):
    return page.evaluate("() => { window.__view.running = false; window.__viewCheck(); return window.__view; }")


def set_zoom(page, scale, lon=0.0, lat=20.0):
    """Put the view at a zoom level through Plotly (the safety net limits it)."""
    page.evaluate("(a) => Plotly.relayout('map', {'geo.projection.scale': a[0], 'geo.center.lon': a[1], "
                  "'geo.center.lat': a[2], 'geo.projection.rotation.lon': 0})", [scale, lon, lat])
    settle(page, 900)


DIRECTIONS = {"right": (1, 0), "left": (-1, 0), "up": (0, -1), "down": (0, 1),
              "up-right": (1, -1), "up-left": (-1, -1), "down-right": (1, 1), "down-left": (-1, 1)}


def hard_drags(page, direction, repeats=3):
    """Drag hard in one direction, several times, always inside the window."""
    box = page.locator("#map .geo").first.bounding_box()
    dx, dy = DIRECTIONS[direction]
    for _ in range(repeats):
        start = (box["x"] + box["width"] * (0.5 - 0.35 * dx), box["y"] + box["height"] * (0.5 - 0.35 * dy))
        end = (box["x"] + box["width"] * (0.5 + 0.35 * dx), box["y"] + box["height"] * (0.5 + 0.35 * dy))
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*end, steps=10)
        page.mouse.up()


def wheel_burst(page, count, delta):
    """`count` wheel events with no pauses (a fast burst), at the map's centre."""
    box = page.locator("#map .geo").first.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(count):
        page.mouse.wheel(0, delta)


def drag_and_wheel_checks(page, label, zooms=(2, 4, 8), directions=tuple(DIRECTIONS)):
    """(a) hard drags at several zoom levels, (b) wheel-out bursts; every frame checked."""
    for zoom in zooms:
        set_zoom(page, zoom)
        start_sampler(page)
        bad_directions = []
        for direction in directions:
            before = len(page.evaluate("window.__view.violations"))
            hard_drags(page, direction)
            settle(page, 300)
            if len(page.evaluate("window.__view.violations")) > before:
                bad_directions.append(direction)
        sampled = stop_sampler(page)
        check(f"{label}: zoom {zoom}x, hard drags {'/'.join(directions) if len(directions) < 8 else 'in 8 directions'}: "
              f"inside the world, no wrap, no rotation, every frame",
              not sampled["violations"] and sampled["frames"] > 20,
              f"{sampled['frames']} frames; bad: {bad_directions}; {sampled['violations'][:3]}")

    click_view(page, "world")
    start_sampler(page)
    wheel_burst(page, 60, 120)
    settle(page, 800)
    sampled = stop_sampler(page)
    check(f"{label}: burst of 60 wheel-outs at World: scale never below World on any frame",
          sampled["minScale"] >= 1 - 1e-6 and not sampled["violations"] and sampled["frames"] > 5,
          f"{sampled['frames']} frames, min scale {sampled['minScale']:.4f}, {sampled['violations'][:2]}")

    set_zoom(page, 1.3)
    start_sampler(page)
    wheel_burst(page, 60, 120)
    settle(page, 800)
    sampled = stop_sampler(page)
    check(f"{label}: burst of 60 wheel-outs from 1.3x: never below World, ends at World",
          sampled["minScale"] >= 1 - 1e-6 and not sampled["violations"] and same_view(view(page), preset("world")),
          f"min scale {sampled['minScale']:.4f}, end {view(page)}, {sampled['violations'][:2]}")


def test_view_limits(browser, scheme):
    """(a) + (b), then (c): the same while Play runs and after a theme switch."""
    context = browser.new_context(color_scheme=scheme, viewport={"width": 1280, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:120]))
    page.goto(BASE + "/index.html")
    wait_for_map(page)
    drag_and_wheel_checks(page, f"[{scheme}]")

    go_to_year_with_slider(page, 1995)
    page.locator("[data-play]").click()                   # Play runs during the next checks
    drag_and_wheel_checks(page, f"[{scheme}] during Play", zooms=(4,), directions=("right", "up-left", "down"))
    playing = page.locator("[data-play]").get_attribute("aria-pressed")
    if playing == "true":
        page.locator("[data-play]").click()
    settle(page)

    other = "dark" if scheme == "light" else "light"
    page.locator(f'[data-theme-button="{other}"]').click()
    settle(page)
    drag_and_wheel_checks(page, f"[{scheme}] after switching to {other}", zooms=(2, 8),
                          directions=("left", "down-right", "up"))
    check(f"[{scheme}] no page errors during the view checks", not errors, "; ".join(errors[:3]))
    context.close()


def test_pinch(browser):
    """Edge only (touch through the DevTools protocol): two-finger pinch."""
    context = browser.new_context(viewport={"width": 1280, "height": 1000}, has_touch=True)
    page = context.new_page()
    page.goto(BASE + "/index.html")
    wait_for_map(page)
    cdp = context.new_cdp_session(page)
    box = page.locator("#map .geo").first.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def pinch(start_gap, end_gap, steps=12):
        def points(gap):
            return [{"x": cx - gap / 2, "y": cy, "id": 1}, {"x": cx + gap / 2, "y": cy, "id": 2}]
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": points(start_gap)})
        for i in range(1, steps + 1):
            gap = start_gap + (end_gap - start_gap) * i / steps
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": points(gap)})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        settle(page, 600)

    start_sampler(page)
    pinch(100, 400)
    zoomed = view(page)["scale"]
    pinch(400, 40)
    pinch(400, 40)
    sampled = stop_sampler(page)
    check("[touch] pinch out zooms in; pinch in stops at World; every frame inside the world",
          zoomed > 2 and sampled["minScale"] >= 1 - 1e-6 and not sampled["violations"]
          and same_view(view(page), preset("world")),
          f"after pinch-out {zoomed:.2f}x, min {sampled['minScale']:.4f}, end {view(page)}, {sampled['violations'][:2]}")
    context.close()


def test_layout(browser):
    for width in (375, 768, 1280):
        context = browser.new_context(viewport={"width": width, "height": 900})
        page = context.new_page()
        page.goto(BASE + "/index.html")
        wait_for_map(page)
        page.locator("#map").hover()
        settle(page, 400)
        boxes = page.evaluate("""() => {
            const box = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };
            const r = s => { const e = document.querySelector(s); return e ? box(e) : null; };
            return {modebar: r('#map .modebar'), map: r('#map'), theme: r('header .segmented'),
                    tools: Array.from(document.querySelectorAll('.map-tools .segmented')).map(box)}; }""")

        def overlap(a, b):
            return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

        clear = boxes["modebar"] is not None and not overlap(boxes["theme"], boxes["modebar"])
        for tool in boxes["tools"]:
            clear = clear and not overlap(tool, boxes["modebar"])
        left = boxes["tools"][0][0] - boxes["map"][0] < 40
        check(f"{width}px: World/Europe, Play and theme toggle clear of the toolbar; view buttons top-left",
              clear and left and len(boxes["tools"]) == 2, json.dumps(boxes))

        expected = min(620, max(360, round(0.75 * width)))
        height = round(boxes["map"][3] - boxes["map"][1])
        plotly_height = page.evaluate("document.getElementById('map')._fullLayout.height")
        check(f"{width}px: map height is clamp(360px, 75vw, 620px) = {expected}px",
              abs(height - expected) <= 1 and abs(plotly_height - expected) <= 1,
              f"div {height}px, Plotly {plotly_height}px")

        click_view(page, "world")
        outside = []
        for place, (lon, lat) in WORLD_MUST_SHOW.items():
            if not screen_point(page, lon, lat)["inside"]:
                outside.append(place)
        check(f"{width}px: World view shows the whole scope (Alaska to New Zealand, Chile)",
              not outside, f"outside: {outside}")
        legend = page.evaluate("""() => { const b = document.querySelector('#map .legend').getBoundingClientRect();
            return [b.left, b.top, b.right, b.bottom]; }""")
        covered = []
        for place, (lon, lat) in LEGEND_MUST_NOT_COVER.items():
            point = screen_point(page, lon, lat)
            if legend[0] <= point["x"] <= legend[2] and legend[1] <= point["y"] <= legend[3]:
                covered.append(place)
        frame_top = page.evaluate("""() => document.getElementById('map')._fullLayout.geo._subplot
            .framework.node().getBoundingClientRect().top""")
        above = width >= 1000 or legend[3] <= frame_top + 1
        check(f"{width}px: legend covers no in-scope country" + ("" if width >= 1000 else ", sits above the map"),
              not covered and above and len(legend_entries(page)) == 4,
              f"covered {covered}, legend {legend}, map top {frame_top}, entries {legend_entries(page)}")
        # Each entry fully visible: inside the map area, not overlapping another entry.
        items = page.evaluate("""() => Array.from(document.querySelectorAll('#map .legend .traces')).map(e => {
            const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; })""")
        map_box = boxes["map"]
        clipped = [i for i, b in enumerate(items)
                   if b[0] < map_box[0] - 1 or b[2] > map_box[2] + 1 or b[1] < map_box[1] - 1 or b[3] > map_box[3] + 1]
        # Real overlap only: more than 2 px in both directions. Firefox gives
        # each entry a 1-px edge, so neighbouring entries share one pixel.
        def real_overlap(a, b):
            return min(a[2], b[2]) - max(a[0], b[0]) > 2 and min(a[3], b[3]) - max(a[1], b[1]) > 2

        overlapping = [(i, j) for i in range(len(items)) for j in range(i + 1, len(items))
                       if real_overlap(items[i], items[j])]
        check(f"{width}px: all 4 legend entries fully visible (inside the map area, no overlaps)",
              len(items) == 4 and not clipped and not overlapping,
              f"clipped {clipped}, overlapping {overlapping}, items {items}")

        click_view(page, "europe")
        outside = []
        for place, (lon, lat) in EUROPE_MUST_SHOW.items():
            if not screen_point(page, lon, lat)["inside"]:
                outside.append(place)
        check(f"{width}px: Europe view shows Iceland, North Cape, Portugal, Cyprus, eastern Turkey",
              not outside, f"outside: {outside}")
        context.close()


def test_themes(browser):
    cases = [("system", "light", "light"), ("system", "dark", "dark"),
             ("light", "dark", "light"), ("dark", "light", "dark")]
    for choice, os_scheme, expected in cases:
        context = browser.new_context(color_scheme=os_scheme, viewport={"width": 1280, "height": 1000})
        page = context.new_page()
        page.goto(BASE + "/index.html")
        wait_for_map(page)
        page.locator(f'[data-theme-button="{choice}"]').click()
        settle(page)
        label = f"theme {choice} (OS {os_scheme})"
        steps = []

        def record(step):
            problems = colors_match(page, expected)
            steps.append((step, problems))

        record("after choosing")
        go_to_year_with_slider(page, 2003)
        record("after year change")
        press_play(page, 2)
        record("after Play")
        click_view(page, "europe")
        record("after Europe")
        click_view(page, "world")
        record("after World")
        bad = [f"{step}: {problems}" for step, problems in steps if problems]
        check(f"{label}: page, land, tiers and legend in {expected} colours throughout", not bad, "; ".join(bad))

        page.reload()
        wait_for_map(page)
        pressed = page.locator('[data-theme-button][aria-pressed="true"]').get_attribute("data-theme-button")
        check(f"{label}: choice remembered after reload", pressed == choice and not colors_match(page, expected),
              f"pressed={pressed}")
        context.close()


def test_hover(page):
    point = page.evaluate("""() => {
        for (const el of document.querySelectorAll('#map .choroplethlocation')) {
            if (!el.__data__ || el.__data__.loc !== 'DEU') continue;
            const b = el.getBoundingClientRect(), toLocal = el.getScreenCTM().inverse();
            for (let fx = 0.3; fx <= 0.7; fx += 0.05) for (let fy = 0.3; fy <= 0.7; fy += 0.05) {
                const x = b.x + b.width * fx, y = b.y + b.height * fy;
                if (el.isPointInFill(new DOMPoint(x, y).matrixTransform(toLocal))) return [x, y];
            }
        }
        return null; }""")
    if point is None:
        check("hover: Germany tooltip", False, "no point on Germany")
        return
    page.mouse.move(*point)
    page.wait_for_selector(".hoverlayer .hovertext", timeout=5000)
    text = page.locator(".hoverlayer .hovertext").first.text_content()
    check("hover: Germany tooltip shows country, tier, essentials, source",
          text.startswith("Germany, 2024") and "Essentials" in text and "Eurostat, COICOP 2018" in text, text[:120])


def main():
    if not (SITE / "index.html").exists():
        sys.exit("site/index.html missing: run src/build_map.py first")
    server = start_server()
    with sync_playwright() as pw:
        for name, launch in [("edge", lambda: pw.chromium.launch(channel="msedge", headless=True)),
                             ("firefox", lambda: pw.firefox.launch(headless=True))]:
            browser = launch()
            print(f"##### {name} {browser.version}")
            for scheme in ("light", "dark"):
                test_csp_and_console(browser, scheme)
            context = browser.new_context(viewport={"width": 1280, "height": 1000})
            page = context.new_page()
            page.goto(BASE + "/index.html")
            wait_for_map(page)
            test_legend_every_year(page)
            test_views(page)
            test_clamp(page)
            test_hover(page)
            context.close()
            for scheme in ("light", "dark"):
                test_view_limits(browser, scheme)
            if name == "edge":
                test_pinch(browser)
            test_layout(browser)
            test_themes(browser)
            browser.close()
    server.shutdown()
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
