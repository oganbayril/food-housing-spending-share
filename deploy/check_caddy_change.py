"""Gate for adding a Caddy site: did anything about the EXISTING sites change?

Usage (on the server, with JSON from `caddy adapt`):
    python3 check_caddy_change.py before.json after.json [new-domain]

Passes (exit 0) only if:
  1. every site in BEFORE still exists in AFTER with an identical route
     (everything Caddy does for that host: headers, proxy, files, ...);
  2. every site in BEFORE still writes its access log with identical
     settings (same file, same format);
  3. the only new site in AFTER is <new-domain>, with exactly one route
     (without <new-domain>: no new site at all, i.e. "nothing changed");
  4. nothing else at the top level changed (other apps, listen addresses).

Why not a plain diff: Caddy numbers some things by position in the WHOLE
config, in file order: access logs (log0, log1, ...) and groups of mutually
exclusive handlers (group0, group1, ...). A new file that sorts first shifts
those numbers for every existing site, so the raw JSON changes although
nothing about the existing sites does. This compares per site, with log
names resolved to their settings and group labels renamed per site.

Tests: python -m unittest discover deploy/tests (fixtures are real
`caddy adapt` output from this project's phase C and phase E).

Standard library only (runs with the server's python3).
"""

import json
import sys


def load(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def canonical(value):
    return json.dumps(value, sort_keys=True)


def normalize_groups(route):
    """Rename a route's auto-generated "group" labels in order of appearance.

    Caddy names groups of mutually exclusive handlers group0, group1, ... with
    one counter for the WHOLE config, in file order. Adding a site that sorts
    first shifts every later site's numbers (seen in phase E: titris
    group3 -> group4) although nothing changes: a label only says "these
    handlers exclude each other". Renaming per route keeps that meaning
    (handlers that shared a group still share one, others still do not), so a
    real regrouping is still caught.
    """
    names = {}

    def walk(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key == "group" and isinstance(item, str):
                    if item not in names:
                        names[item] = f"g{len(names)}"
                    result[key] = names[item]
                else:
                    result[key] = walk(item)
            return result
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(route)


def sites(config):
    """{host: (route, resolved log settings)} for every server in the config."""
    logs = config.get("logging", {}).get("logs", {})
    result = {}
    for server in config["apps"]["http"]["servers"].values():
        logger_names = server.get("logs", {}).get("logger_names", {})
        for route in server.get("routes", []):
            hosts = []
            for match in route.get("match", []):
                hosts.extend(match.get("host", []))
            for host in hosts:
                resolved_logs = []
                for name in logger_names.get(host, []):
                    settings = dict(logs.get(name, {}))
                    settings.pop("include", None)  # contains the numbered name
                    resolved_logs.append(settings)
                if host in result:
                    raise SystemExit(f"FAIL: {host} appears in more than one route")
                result[host] = (canonical(normalize_groups(route)), canonical(resolved_logs))
    return result


def rest(config):
    """Everything except the HTTP routes, per-host log names and the logs."""
    copy = json.loads(json.dumps(config))
    copy.pop("logging", None)
    for server in copy["apps"]["http"]["servers"].values():
        server.pop("routes", None)
        server.pop("logs", None)
    return canonical(copy)


def compare(before, after, new_domain=None):
    """List of problems (empty = pass). new_domain=None: expect no new site."""
    before_sites, after_sites = sites(before), sites(after)
    problems = []

    for host, (route, log) in before_sites.items():
        if host not in after_sites:
            problems.append(f"{host}: missing after the change")
            continue
        if after_sites[host][0] != route:
            problems.append(f"{host}: route changed")
        if after_sites[host][1] != log:
            problems.append(f"{host}: log settings changed")

    added = sorted(set(after_sites) - set(before_sites))
    if new_domain is None:
        expected = []
    else:
        expected = [new_domain]
    if added != expected:
        problems.append(f"expected new site(s) {expected}, got {added}")

    if rest(before) != rest(after):
        problems.append("something outside the site routes and logs changed")
    return problems


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit("usage: check_caddy_change.py before.json after.json [new-domain]")
    before, after = load(sys.argv[1]), load(sys.argv[2])
    new_domain = sys.argv[3] if len(sys.argv) == 4 else None

    problems = compare(before, after, new_domain)
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        sys.exit(1)
    existing = sorted(sites(before))
    added = f"only new site: {new_domain}" if new_domain else "no new site"
    print(f"OK: {len(existing)} existing site(s) unchanged ({', '.join(existing)}); {added}")


if __name__ == "__main__":
    main()
