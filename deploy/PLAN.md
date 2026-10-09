# Deployment plan

Goal: serve `site/index.html` and `site/shares.csv` as a static site from the
existing Hetzner VPS (`89.167.25.74`) with Caddy, next to the other projects
on the box, without any project overwriting another's Caddy configuration.

Hostname: `food-housing-spending-share.duckdns.org` (already resolves to the
VPS IP).

Each phase ends with a check and a rollback, and runs only after the owner
confirms the previous one.

## What is on the server (phase A, 2026-10-08, read-only)

The VPS **already uses one file per site** (set up with the titris project
on 2026-09-20), so the original plan to restructure into `sites/` was dropped:

| File | Contents |
|---|---|
| `/etc/caddy/Caddyfile` | only `import sites-enabled/*` |
| `sites-enabled/00-existing.conf` | germany-real-estate.duckdns.org (reverse proxy to :8000) |
| `sites-enabled/titris.conf` | titris.duckdns.org (static build + API on :8001) |
| `Caddyfile.bak.1789863171` | the old single-site Caddyfile (= `00-existing.conf`) |

Caddy v2.11.4, running since 2026-09-20; real-estate `/health` 200; certificate
(Let's Encrypt) valid to 2026-12-02. `/srv` empty.

**Risk found:** the real-estate `deploy/setup.sh` still writes the whole
`/etc/caddy/Caddyfile` from its single-site template. Re-running it would
remove the `import` line and take **titris** (and later this site) offline.
Phase D fixes that. Until then: do not re-run the real-estate `setup.sh`
(`update.sh` is safe; it does not touch Caddy).

## Phase B: back up (done 2026-10-08)

```bash
STAMP=20261008-2258
tar -czf /root/caddy-backup-$STAMP.tar.gz -C /etc caddy
caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /root/caddy-before-$STAMP.json
```

Both files downloaded to `C:\Users\Ogi\caddy-backups\` (checksums match).
The "before" JSON is produced with `caddy adapt` from the files on disk, the
same way as the "after" JSON in phase C, so the comparison is like for like.

## Phase C: rename `00-existing.conf` to `realestate.conf` (done 2026-10-08)

Gives the real-estate repo a clearly named file to own (phase D). Import
order is unchanged: Caddy imports `sites-enabled/*` alphabetically, and both
`00-existing.conf` and `realestate.conf` sort before `titris.conf`.

Gate: reload only if `caddy validate` passes **and** the adapted JSON is
identical to the phase B "before"; otherwise the rename is undone, no reload.

```bash
set -e
STAMP=20261008-2258
cd /etc/caddy/sites-enabled
mv 00-existing.conf realestate.conf
if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
   && caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /root/caddy-after.json \
   && diff <(python3 -m json.tool --sort-keys /root/caddy-before-$STAMP.json) \
           <(python3 -m json.tool --sort-keys /root/caddy-after.json); then
  echo "IDENTICAL -> reloading"; systemctl reload caddy
else
  echo "NOT identical or invalid -> reverting rename, no reload"; mv realestate.conf 00-existing.conf; exit 1
fi
```

Check afterwards: real-estate `/health` 200, same certificate; titris 200;
no errors in `journalctl -u caddy`.

Rollback: `mv realestate.conf 00-existing.conf && systemctl reload caddy`
(or restore the phase B tarball).

## Phase D: real-estate `setup.sh` stops overwriting the main Caddyfile (done 2026-10-08)

A separate commit in the **germany-real-estate-api** repo:
- `setup.sh` writes `/etc/caddy/sites-enabled/realestate.conf` instead of
  `/etc/caddy/Caddyfile`;
- it creates `/etc/caddy/Caddyfile` with `import sites-enabled/*` only if
  that file does not exist, so other projects' sites are never touched;
- `deploy/README.md` updated to match.

Tested locally, not on the VPS: generate the file to a temporary path with the
same `sed` and diff it against the live `realestate.conf`.

## Phase E: add this site

### Pre-checks (done 2026-10-09)

- DNS: `food-housing-spending-share.duckdns.org` -> `89.167.25.74` on the local
  resolver, 1.1.1.1 and 8.8.8.8; no AAAA record; port 80 reaches Caddy.
- **Content-Security-Policy**, tested before any upload. `site/` was served
  locally with the same headers as `deploy/food-housing.caddy`, and the page
  was driven with Playwright in **Edge 154 and Firefox 155, light and dark**:
  load, hover tooltip, World/Europe, slider, Play, PNG download, CSV download.
  Result in all four runs: **0 CSP violations, 0 console errors, 0 failed
  requests**. Negative control: a copy of the page with one extra, unhashed
  inline script was blocked in all four runs (the policy is enforced).

  Policy (a `<meta>`, first element in `<head>`, written by
  `src/build_map.py` with script hashes computed from the same page, so they
  cannot go stale when the data changes):

  ```
  default-src 'none'; script-src 'sha256-...' (the page's 4 inline scripts);
  style-src 'unsafe-inline'; img-src 'self' blob:;
  connect-src https://cdn.plot.ly; base-uri 'none'; form-action 'none'
  ```

  | Directive | Why |
  |---|---|
  | `script-src` hashes | 4 inline scripts (Plotly config, bundle, figure, page script); no `'unsafe-inline'`, no `'unsafe-eval'` (never requested) |
  | `style-src 'unsafe-inline'` | Plotly sets `style="..."` and injects `<style>` at runtime |
  | `img-src 'self' blob:` | favicon; Plotly's PNG export draws via a `blob:` image (`data:` never requested) |
  | `connect-src https://cdn.plot.ly` | map outlines: `https://cdn.plot.ly/un/world_50m.json` |

  Caddy adds `Content-Security-Policy: frame-ancestors 'none'` as a header
  (not possible in a `<meta>`); browsers enforce both policies.
- Plotly's **"Share chart..." button removed**: it uploads the chart to
  Plotly Cloud. Select/lasso tools and the Plotly logo removed too.
- **HSTS** for this host only: `max-age=31536000`, no `includeSubDomains`,
  no `preload`.

### E1: upload (nothing live changes)

```bash
ssh root@89.167.25.74 "mkdir -p /srv/food-housing-share && chmod 755 /srv/food-housing-share"
scp site/index.html site/shares.csv site/favicon.svg root@89.167.25.74:/srv/food-housing-share/
ssh root@89.167.25.74 "chmod 644 /srv/food-housing-share/*"
scp deploy/food-housing.caddy deploy/check_caddy_change.py root@89.167.25.74:/root/
# the uploaded files must be byte-identical to the tested ones
sha256sum site/index.html site/shares.csv site/favicon.svg
ssh root@89.167.25.74 "cd /srv/food-housing-share && sha256sum index.html shares.csv favicon.svg"
```

Stop if any checksum differs.

### E2: install, gated

Gate: `caddy validate` passes **and** `check_caddy_change.py` confirms the
two existing sites are unchanged (route and resolved log settings per host;
log numbering may shift because `food-housing.conf` sorts first) and the only
new site is this one. Otherwise the new file is removed and Caddy is not
reloaded.

```bash
ssh root@89.167.25.74 'bash -s' <<'REMOTE'
set -e
DOMAIN=food-housing-spending-share.duckdns.org
CONF=/etc/caddy/sites-enabled/food-housing.conf
[ ! -e "$CONF" ] || { echo "$CONF already exists, stopping"; exit 1; }
caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /root/caddy-before-e.json
sed "s/FOODHOUSING_DOMAIN/$DOMAIN/" /root/food-housing.caddy > "$CONF"
if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile    && caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /root/caddy-after-e.json    && python3 /root/check_caddy_change.py /root/caddy-before-e.json /root/caddy-after-e.json "$DOMAIN"; then
  systemctl reload caddy; echo "reloaded"
else
  rm -f "$CONF"; echo "check failed -> removed $CONF, no reload"; exit 1
fi
REMOTE
```

### E3: re-check all three sites

- germany-real-estate: `/health` 200 (GET and HEAD), same certificate.
- titris: 200.
- food-housing: certificate issued on the first HTTPS request (retry for up
  to a minute); `/` 200 `text/html` with HSTS `max-age=31536000` only,
  `frame-ancestors` CSP header, nosniff; `/shares.csv` with
  `Content-Disposition: attachment`; `/favicon.svg` 200.
- `journalctl -u caddy`: no errors since the reload.

Rollback: `rm /etc/caddy/sites-enabled/food-housing.conf && systemctl reload caddy`.

## Updating the site later

The data changes about once a year. Rebuild locally (the CSP hashes are
regenerated with the page), re-run the browser test, then copy the files and
compare checksums; no Caddy reload is needed for static files:

```bash
uv run python src/build_map.py
scp site/index.html site/shares.csv site/favicon.svg root@89.167.25.74:/srv/food-housing-share/
sha256sum site/index.html && ssh root@89.167.25.74 "sha256sum /srv/food-housing-share/index.html"
```

## Known follow-ups (not blocking)

- The page loads the map outlines (`world_50m.json`) from Plotly's CDN at
  view time. Self-hosting that file would remove the only third-party request.
- titris is left as it is.
