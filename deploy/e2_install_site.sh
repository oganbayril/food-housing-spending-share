#!/usr/bin/env bash
#
# Phase E2: install the food-housing site into Caddy, gated.
# Run on the server as root:  bash /root/e2_install_site.sh
#
# Lessons from the first two attempts (deploy/PLAN.md):
# - `caddy validate` run as ROOT created the new log file owned by root, which
#   the running Caddy (user caddy) then could not open: the reload failed.
#   So the log is pre-created owned by caddy, and validation runs as caddy.
# - With `set -e`, a failed reload exited before the cleanup and left the new
#   config on disk. So there is no `set -e`: every failure path is explicit
#   and goes through clean_up_and_stop.
#
# Every path can be overridden through an environment variable (defaults are
# the real ones), so the failure paths can be tested off the server with fake
# caddy/runuser/systemctl/python3 commands: deploy/tests/test_e2_install_site.sh
set -u

DOMAIN="${E2_DOMAIN:-food-housing-spending-share.duckdns.org}"
CADDYFILE="${E2_CADDYFILE:-/etc/caddy/Caddyfile}"
CONF="${E2_CONF:-/etc/caddy/sites-enabled/food-housing.conf}"
LOG="${E2_LOG:-/var/log/caddy/food-housing.log}"
TEMPLATE="${E2_TEMPLATE:-/root/food-housing.caddy}"
CHECKER="${E2_CHECKER:-/root/check_caddy_change.py}"
STATE_DIR="${E2_STATE_DIR:-/root}"
CADDY_USER="${E2_CADDY_USER:-caddy}"
CADDY_HOME="${E2_CADDY_HOME:-$(getent passwd "$CADDY_USER" | cut -d: -f6)}"
log_created=0

# Undo everything this script created, then stop.
clean_up_and_stop() {
  echo "FAILED: $1"
  rm -f "$CONF"
  echo "  removed $CONF"
  if [ "$log_created" = 1 ] && [ -f "$LOG" ] && [ ! -s "$LOG" ]; then
    rm "$LOG"
    echo "  removed empty $LOG (created by this run)"
  fi
  echo "  caddy keeps running its previous config"
  exit 1
}

validate_as_caddy() {
  runuser -u "$CADDY_USER" -- env HOME="$CADDY_HOME" \
    caddy validate --config "$CADDYFILE" --adapter caddyfile
}

# --- preconditions -------------------------------------------------------------
if [ -e "$CONF" ]; then
  echo "$CONF already exists, stopping (nothing changed)"
  exit 1
fi
if [ -e "$LOG" ] && [ "$(stat -c %U "$LOG")" != "$CADDY_USER" ]; then
  echo "$LOG exists and is not owned by $CADDY_USER, stopping (nothing changed)"
  exit 1
fi

# --- 1. config as it is now (the gate's reference) ----------------------------
caddy adapt --config "$CADDYFILE" --adapter caddyfile > "$STATE_DIR/caddy-before-e.json" \
  || { echo "caddy adapt of the CURRENT config failed, stopping (nothing changed)"; exit 1; }

# --- 2. the new site's log, owned like the other logs -------------------------
if [ ! -e "$LOG" ]; then
  install -o "$CADDY_USER" -g "$CADDY_USER" -m 600 /dev/null "$LOG"
  log_created=1
  echo "created $LOG ($CADDY_USER:$CADDY_USER 600)"
fi

# --- 3. the new site's config -------------------------------------------------
sed "s/FOODHOUSING_DOMAIN/$DOMAIN/" "$TEMPLATE" > "$CONF"
echo "wrote $CONF"

# --- 4. gate: valid as the service user, and existing sites unchanged ---------
validate_as_caddy \
  || clean_up_and_stop "caddy validate (as user $CADDY_USER) failed"
caddy adapt --config "$CADDYFILE" --adapter caddyfile > "$STATE_DIR/caddy-after-e.json" \
  || clean_up_and_stop "caddy adapt of the new config failed"
python3 "$CHECKER" "$STATE_DIR/caddy-before-e.json" "$STATE_DIR/caddy-after-e.json" "$DOMAIN" \
  || clean_up_and_stop "existing sites would change"

# --- 5. reload; a failed reload is treated like a failed gate ------------------
reload_started=$(date '+%Y-%m-%d %H:%M:%S')
systemctl reload caddy \
  || clean_up_and_stop "systemctl reload caddy failed (see journalctl -u caddy)"

# --- 6. confirm what Caddy is actually running --------------------------------
live_hosts=$(curl -s localhost:2019/config/apps/http/servers/srv0/routes \
  | python3 -c 'import json, sys
hosts = []
for route in json.load(sys.stdin):
    for match in route.get("match", []):
        hosts.extend(match.get("host", []))
print(" ".join(sorted(hosts)))')
echo "live hosts: $live_hosts"
echo "--- journalctl -u caddy since the reload (access log lines omitted)"
journalctl -u caddy --since "$reload_started" --no-pager | grep -v "http.log.access"

expected="${E2_EXPECTED_HOSTS:-food-housing-spending-share.duckdns.org germany-real-estate.duckdns.org titris.duckdns.org}"
if [ "$live_hosts" != "$expected" ]; then
  echo "FAILED: Caddy reloaded, but the live hosts are not the expected three."
  echo "  NOT rolling back automatically: the reload succeeded, so check first."
  exit 1
fi
echo "reloaded"
