"""Gate for adding a Caddy site: did anything about the EXISTING sites change?

Usage (on the server, with JSON from `caddy adapt`):
    python3 check_caddy_change.py before.json after.json <new-domain>

Passes (exit 0) only if:
  1. every site in BEFORE still exists in AFTER with an identical route
     (everything Caddy does for that host: headers, proxy, files, ...);
  2. every site in BEFORE still writes its access log with identical
     settings (same file, same format);
  3. the only new site in AFTER is <new-domain>, with exactly one route;
  4. nothing else at the top level changed (other apps, listen addresses).

Why not a plain diff: Caddy numbers access logs by file order (log0, log1,
...). A new file that sorts first renumbers the existing logs, so the raw
JSON changes although nothing about the existing sites does. This compares
per site, with log names resolved to their settings.

Standard library only (runs with the server's python3).
"""

import json
import sys


def load(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def canonical(value):
    return json.dumps(value, sort_keys=True)


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
                result[host] = (canonical(route), canonical(resolved_logs))
    return result


def rest(config):
    """Everything except the HTTP routes, per-host log names and the logs."""
    copy = json.loads(json.dumps(config))
    copy.pop("logging", None)
    for server in copy["apps"]["http"]["servers"].values():
        server.pop("routes", None)
        server.pop("logs", None)
    return canonical(copy)


def main():
    before_path, after_path, new_domain = sys.argv[1], sys.argv[2], sys.argv[3]
    before, after = load(before_path), load(after_path)
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
    if added != [new_domain]:
        problems.append(f"expected exactly one new site {new_domain}, got {added}")

    if rest(before) != rest(after):
        problems.append("something outside the site routes and logs changed")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        sys.exit(1)
    print(f"OK: {len(before_sites)} existing site(s) unchanged "
          f"({', '.join(sorted(before_sites))}); only new site: {new_domain}")


if __name__ == "__main__":
    main()
