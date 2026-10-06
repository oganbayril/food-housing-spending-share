# Deployment plan (not run yet)

Goal: serve `site/index.html` and `site/shares.csv` as a static site from the
existing Hetzner VPS with Caddy, next to the germany-real-estate API, without
the two projects overwriting each other's Caddy configuration.

**Status: plan only. Nothing below has been run on the VPS.** Each phase ends
with a check and a rollback. Phases A-C change only how the existing
real-estate site is configured, not what it serves; this site is added only in
phase E, after the real-estate site has been confirmed working on the new
layout.

## Why the change is needed

The real-estate project's `deploy/setup.sh` writes the whole
`/etc/caddy/Caddyfile` from its single-site template (line 81:
`sed ... deploy/Caddyfile > /etc/caddy/Caddyfile`). Adding this site to that
file would be erased the next time `setup.sh` runs. The fix: the main
Caddyfile only imports one file per site from `/etc/caddy/sites/`, and each
project owns its own file there.

## Before starting: decisions and inputs

- **Hostname** for this site, registered at duckdns.org and pointed at the
  VPS IP (same IP as `germany-real-estate.duckdns.org`). Placeholder below:
  `FOODHOUSING_DOMAIN`. To be chosen by the owner.
- SSH access as used for the real-estate deploy (`ssh root@<host>`).
- A quiet time window: a Caddy reload is graceful, but phase C is where a
  mistake would affect the live API.

## Phase A: look, don't touch (read-only)

```bash
ssh root@<host>
caddy version
ls -la /etc/caddy/
cat /etc/caddy/Caddyfile                      # expect the single real-estate block
systemctl status caddy --no-pager
journalctl -u caddy --since "1 hour ago" --no-pager | tail -20
curl -s https://germany-real-estate.duckdns.org/health
# note the current certificate's issuer and expiry, to compare later
echo | openssl s_client -connect germany-real-estate.duckdns.org:443 \
  -servername germany-real-estate.duckdns.org 2>/dev/null | openssl x509 -noout -issuer -enddate
```

Stop here if the Caddyfile is not what the real-estate template would produce
(someone edited it by hand): adjust the plan first.

## Phase B: back up

```bash
STAMP=$(date +%Y%m%d-%H%M)
cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$STAMP
# the "before" config as Caddy's JSON, for the equivalence check in phase C
caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /root/caddy-before-$STAMP.json
```

Run phases B and C in the same SSH session: `$STAMP` is used again in phase C
(or note its value and set it again).

Also copy the backup off the server (from the local machine):

```bash
scp root@<host>:/etc/caddy/Caddyfile.bak-* ./caddy-backups/
```

## Phase C: move to one file per site (real-estate only)

```bash
mkdir -p /etc/caddy/sites
# the current block, unchanged, becomes the real-estate site file
cp /etc/caddy/Caddyfile /etc/caddy/sites/realestate.caddy
# the main Caddyfile now only imports the site files
printf 'import sites/*.caddy\n' > /etc/caddy/Caddyfile
```

Check before reloading:

```bash
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
# the new layout must produce EXACTLY the same running config as before
caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /root/caddy-after.json
diff <(python3 -m json.tool --sort-keys /root/caddy-before-$STAMP.json) \
     <(python3 -m json.tool --sort-keys /root/caddy-after.json) && echo "IDENTICAL"
```

Only if validation passes **and** the diff says IDENTICAL:

```bash
systemctl reload caddy
```

(If a reload is given an invalid config, Caddy rejects it and keeps running
the old one; the `validate` step is there so it never gets that far.)

**Test the real-estate site** on the new layout:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://germany-real-estate.duckdns.org/health   # 200
curl -sI https://germany-real-estate.duckdns.org/docs | head -5                             # 200, HSTS header
echo | openssl s_client -connect germany-real-estate.duckdns.org:443 \
  -servername germany-real-estate.duckdns.org 2>/dev/null | openssl x509 -noout -issuer -enddate  # same as phase A
journalctl -u caddy --since "10 min ago" --no-pager | grep -i -E "error|warn" || echo "no errors"
```

Then open the demo page in a browser and submit one prediction. Leave it
running (e.g. a day) before phase E.

**Rollback (phase C):**

```bash
cp -a /etc/caddy/Caddyfile.bak-$STAMP /etc/caddy/Caddyfile
systemctl reload caddy
```

## Phase D: stop `setup.sh` from undoing phase C (real-estate repo)

A change in the **germany-real-estate-api** repo, as its own commit there:
`setup.sh` should write `/etc/caddy/sites/realestate.caddy` instead of
`/etc/caddy/Caddyfile`, and create the main Caddyfile with the `import` line
only if it does not exist yet. Update its `deploy/README.md` to match.

Until that change is deployed: **do not re-run the real-estate `setup.sh`**
(`update.sh` is safe; it does not touch Caddy).

## Phase E: add this site

1. DuckDNS: register `FOODHOUSING_DOMAIN`, point it at the VPS IP, and check
   from the local machine: `nslookup FOODHOUSING_DOMAIN`.
2. Files (from the local machine, after `uv run python src/build_map.py`):

   ```bash
   ssh root@<host> "mkdir -p /srv/food-housing-share && chmod 755 /srv/food-housing-share"
   scp site/index.html site/shares.csv root@<host>:/srv/food-housing-share/
   ssh root@<host> "chmod 644 /srv/food-housing-share/*"
   scp deploy/food-housing.caddy root@<host>:/root/food-housing.caddy
   ```

   Caddy only needs to read these files; nothing on the server writes them.
3. Site config, on the server:

   ```bash
   sed "s/FOODHOUSING_DOMAIN/<the real hostname>/" /root/food-housing.caddy \
     > /etc/caddy/sites/food-housing.caddy
   caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   systemctl reload caddy
   ```

4. Test:

   ```bash
   curl -sI https://<the real hostname>/ | head -5                # 200, text/html, HSTS
   curl -sI https://<the real hostname>/shares.csv | grep -i disposition   # attachment
   curl -s -o /dev/null -w "%{http_code}\n" https://germany-real-estate.duckdns.org/health  # still 200
   ```

   Then in a browser: the map loads, the slider moves, hover works, dark mode
   follows the system setting, World / Europe zoom works, the CSV downloads.
   Caddy requests the certificate on the first request; if that fails, check
   `journalctl -u caddy` (DNS not propagated yet is the usual cause).

**Rollback (phase E):**

```bash
rm /etc/caddy/sites/food-housing.caddy
systemctl reload caddy
```

## Updating the site later

The data changes about once a year. Rebuild locally and copy the two files;
no Caddy reload is needed for static files:

```bash
uv run python src/build_map.py
scp site/index.html site/shares.csv root@<host>:/srv/food-housing-share/
```

## Known follow-ups (not blocking)

- The page loads the map outlines (`world_50m.json`) from Plotly's CDN at
  view time. Self-hosting that file would remove the only third-party request.
- No Content-Security-Policy yet: Plotly's inline scripts would need a
  policy tested in the browser before it is enabled.
