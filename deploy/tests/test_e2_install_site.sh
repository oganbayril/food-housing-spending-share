#!/usr/bin/env bash
#
# Failure-path tests for deploy/e2_install_site.sh, off the server.
#
# Fake caddy / runuser / systemctl / python3 / curl / journalctl / install go
# first on PATH. FAIL=<step> makes one of them fail; each case runs in its own
# scratch directory and checks exit code, last line, and which files remain.
#
# Run from the project root:  bash deploy/tests/test_e2_install_site.sh
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="${E2_SCRIPT_UNDER_TEST:-$ROOT/deploy/e2_install_site.sh}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
pass=0
fail=0

# --- fakes ---------------------------------------------------------------------
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/caddy" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  adapt)
    count=$(( $(cat "$FAKE_STATE/adapt_count" 2>/dev/null || echo 0) + 1 ))
    echo "$count" > "$FAKE_STATE/adapt_count"
    if [ "${FAIL:-}" = adapt_before ] && [ "$count" = 1 ]; then exit 1; fi
    if [ "${FAIL:-}" = adapt_after ] && [ "$count" = 2 ]; then exit 1; fi
    echo '{}' ;;
  validate)
    if [ "${FAIL:-}" = validate ]; then echo "Error: fake validate failure"; exit 1; fi
    echo "Valid configuration" ;;
esac
EOF
cat > "$BIN/runuser" <<'EOF'
#!/usr/bin/env bash
# runuser -u USER -- command...  ->  run the command (as the current user)
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
shift
exec "$@"
EOF
cat > "$BIN/python3" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then cat > /dev/null; echo "$FAKE_LIVE_HOSTS"; exit 0; fi
if [ "${FAIL:-}" = checker ]; then echo "FAIL: fake: existing site changed"; exit 1; fi
echo "OK: fake checker"
EOF
cat > "$BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
if [ "${FAKE_CADDY_WRITES_LOG:-0}" = 1 ]; then echo "caddy wrote a line" >> "$E2_LOG"; fi
if [ "${FAIL:-}" = reload ]; then echo "Job for caddy.service failed."; exit 1; fi
EOF
cat > "$BIN/curl" <<'EOF'
#!/usr/bin/env bash
echo '[]'
EOF
cat > "$BIN/journalctl" <<'EOF'
#!/usr/bin/env bash
echo "fake journal: Reloaded caddy.service"
EOF
cat > "$BIN/install" <<'EOF'
#!/usr/bin/env bash
# install -o U -g G -m 600 /dev/null FILE  ->  create an empty FILE
for last in "$@"; do :; done
: > "$last"
EOF
chmod +x "$BIN"/*

ALL_HOSTS="food-housing-spending-share.duckdns.org germany-real-estate.duckdns.org titris.duckdns.org"
ME="$(stat -c %U "$SCRIPT")"   # owner of local files, stands in for "caddy"

# --- one scratch "server" per case ---------------------------------------------
setup() {
  CASE="$WORK/$1"
  mkdir -p "$CASE/sites-enabled" "$CASE/log" "$CASE/state"
  echo "import sites-enabled/*" > "$CASE/Caddyfile"
  export E2_CADDYFILE="$CASE/Caddyfile"
  export E2_CONF="$CASE/sites-enabled/food-housing.conf"
  export E2_LOG="$CASE/log/food-housing.log"
  export E2_TEMPLATE="$ROOT/deploy/food-housing.caddy"
  export E2_CHECKER="$CASE/check_caddy_change.py"
  export E2_STATE_DIR="$CASE/state"
  export E2_CADDY_USER="$ME"
  export E2_CADDY_HOME="$CASE"
  export FAKE_STATE="$CASE/state"
  export FAKE_LIVE_HOSTS="$ALL_HOSTS"
  export FAKE_CADDY_WRITES_LOG=0
  export FAIL=""
}

run() {
  PATH="$BIN:$PATH" bash "$SCRIPT" > "$CASE/out.log" 2>&1
  echo $? > "$CASE/exit"
}

check() {  # description, condition
  if eval "$2"; then
    echo "    PASS  $1"; pass=$((pass + 1))
  else
    echo "    FAIL  $1"; fail=$((fail + 1))
    sed 's/^/          | /' "$CASE/out.log"
  fi
}

exit_is() { [ "$(cat "$CASE/exit")" = "$1" ]; }
last_line_is() { [ "$(tail -n 1 "$CASE/out.log")" = "$1" ]; }

for step in validate adapt_after checker reload; do
  echo "case: $step fails, no log before the run"
  setup "fail_$step"; FAIL=$step; run
  check "exit 1"                          'exit_is 1'
  check "new conf removed"                '[ ! -e "$E2_CONF" ]'
  check "log created by this run removed" '[ ! -e "$E2_LOG" ]'
  check "says FAILED"                     'grep -q "^FAILED: " "$CASE/out.log"'
done

echo "case: reload fails, an EMPTY log existed before the run"
setup pre_log; FAIL=reload
install -m 600 /dev/null "$E2_LOG"
run
check "exit 1"                            'exit_is 1'
check "new conf removed"                  '[ ! -e "$E2_CONF" ]'
check "pre-existing log left alone"       '[ -f "$E2_LOG" ]'

echo "case: reload fails, log created by this run but written to (not empty)"
setup log_written; FAIL=reload; FAKE_CADDY_WRITES_LOG=1; run
check "exit 1"                            'exit_is 1'
check "new conf removed"                  '[ ! -e "$E2_CONF" ]'
check "non-empty log left alone"          '[ -s "$E2_LOG" ]'

echo "case: adapt of the CURRENT config fails (before anything is created)"
setup adapt_before; FAIL=adapt_before; run
check "exit 1"                            'exit_is 1'
check "no conf created"                   '[ ! -e "$E2_CONF" ]'
check "no log created"                    '[ ! -e "$E2_LOG" ]'

echo "case: the conf already exists"
setup conf_exists
echo "# someone else's file" > "$E2_CONF"
run
check "exit 1"                            'exit_is 1'
check "existing conf untouched"           '[ "$(cat "$E2_CONF")" = "# someone else'"'"'s file" ]'
check "no log created"                    '[ ! -e "$E2_LOG" ]'

echo "case: a log exists but is owned by another user"
setup foreign_log
echo "old" > "$E2_LOG"
E2_CADDY_USER="someone-else"; run
check "exit 1"                            'exit_is 1'
check "no conf created"                   '[ ! -e "$E2_CONF" ]'
check "log untouched"                     '[ "$(cat "$E2_LOG")" = old ]'

echo "case: everything succeeds"
setup success; run
check "exit 0"                            'exit_is 0'
check "last line is 'reloaded'"           'last_line_is reloaded'
check "conf installed, domain filled in"  'grep -q "^food-housing-spending-share.duckdns.org {" "$E2_CONF"'
check "log present"                       '[ -f "$E2_LOG" ]'

echo "case: reload succeeds but the live hosts are not the expected three"
setup wrong_hosts; FAKE_LIVE_HOSTS="germany-real-estate.duckdns.org titris.duckdns.org"; run
check "exit 1"                            'exit_is 1'
check "last line is not 'reloaded'"       '! last_line_is reloaded'
check "no automatic rollback (by design)" '[ -e "$E2_CONF" ]'

echo
echo "passed: $pass  failed: $fail"
[ "$fail" = 0 ]
