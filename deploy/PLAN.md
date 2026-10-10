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

### E1: upload (done 2026-10-09)

```bash
ssh root@89.167.25.74 "mkdir -p /srv/food-housing-share && chmod 755 /srv/food-housing-share"
scp site/index.html site/shares.csv site/favicon.svg root@89.167.25.74:/srv/food-housing-share/
ssh root@89.167.25.74 "chmod 644 /srv/food-housing-share/*"
scp deploy/food-housing.caddy deploy/check_caddy_change.py deploy/e2_install_site.sh root@89.167.25.74:/root/
```

Then an automated diff of `sha256sum` local vs. server for every uploaded
file (Git Bash's `*` binary marker normalised); stop if anything differs.

### E2: install, gated (done 2026-10-09, third attempt)

```bash
ssh root@89.167.25.74 'bash /root/e2_install_site.sh'   # last line must be "reloaded"
```

`deploy/e2_install_site.sh` (failure paths tested off the server by
`deploy/tests/test_e2_install_site.sh`):
1. stops, changing nothing, if `food-housing.conf` exists or the site's log
   exists and is not owned by `caddy`;
2. saves the current config (`caddy adapt`) as the reference;
3. pre-creates `/var/log/caddy/food-housing.log` owned by `caddy`, mode 600;
4. writes `sites-enabled/food-housing.conf` from the template;
5. gate: `caddy validate` **as the caddy user** (`runuser`, the service's
   `HOME`), `caddy adapt`, and `check_caddy_change.py` (existing sites
   unchanged per host; only new site is this one);
6. `systemctl reload caddy`; a failed gate **or a failed reload** removes the
   new conf, and the log only if this run created it and it is still empty;
7. checks the admin API lists exactly the three hosts and prints the journal
   lines from the reload; last line `reloaded`.

What the first two attempts taught (both left the live sites untouched):
- **Attempt 1** stopped at the gate: `titris.duckdns.org: route changed`. A
  false positive: Caddy's auto-generated group label shifted (group3 ->
  group4) because `food-housing.conf` sorts first. The checker now renames
  groups per site (tests with the real before/after files as fixtures).
- **Attempt 2** passed the gate but the reload failed:
  `open /var/log/caddy/food-housing.log: permission denied`. Attempt 1's
  `caddy validate`, run as root, had created the log file owned by root;
  Caddy runs as `caddy`. And `set -e` made the failed reload skip the
  cleanup, leaving the new conf on disk (disk and running config disagreed
  until the rollback: a restart would have failed). Rolled back, verified
  (checker in no-new-site mode vs. the live admin API; `caddy validate` as
  `caddy`), then fixed in the script above.

### E3: re-check all three sites (done 2026-10-09)

- germany-real-estate: `GET` and `HEAD /health` 200, `HEAD /` 200, same
  certificate (notAfter 2026-12-02), its own headers unchanged.
- titris: 200.
- food-housing: certificate issued on the first HTTPS request (retry for up
  to a minute; took ~2 s); `/` 200 `text/html`; HSTS exactly
  `max-age=31536000`; `Content-Security-Policy: frame-ancestors 'none'`;
  nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, no
  `Server` header; served `index.html`, `shares.csv`, `favicon.svg`
  byte-identical to the tested files; `/shares.csv` with
  `Content-Disposition: attachment`; `/favicon.svg` 200 `image/svg+xml`.
- **The CSP `<meta>` is the first element in `<head>`: the line right after
  `<head>`** (not a fixed line number; an earlier version of this check
  looked at line 3, which is `<head>` itself):
  `curl -s https://<host>/ | awk 'found { print; exit } /^<head>$/ { found = 1 }'`
- `journalctl -u caddy` since the reload: no warnings or errors other than
  the standard port-80 "HTTP/2 / HTTP/3 skipped because it requires TLS".
- Admin API host list: the three hosts.
- Note: after a failed then successful reload, `systemctl status caddy`
  keeps showing the failed reload's message in its `Status:` line until the
  next restart. The `ExecReload` line (`status=0/SUCCESS`), the journal and
  the admin API are authoritative.

Rollback: `rm /etc/caddy/sites-enabled/food-housing.conf && systemctl reload caddy`
(leave `/var/log/caddy/food-housing.log`, owned by `caddy`).

## Updating the site later

The data changes about once a year. Rebuild locally (the CSP hashes are
regenerated with the page), re-run the browser test, then copy the files and
compare checksums; no Caddy reload is needed for static files:

```bash
uv run python src/build_map.py
uv run --with playwright --with pillow python tests/browser/test_map_page.py   # must be all PASS
scp site/index.html site/shares.csv site/favicon.svg root@89.167.25.74:/srv/food-housing-share/
# then the automated sha256sum diff, local vs. server
```

## Known follow-ups (not blocking)

- The page loads the map outlines (`world_50m.json`) from Plotly's CDN at
  view time. Self-hosting that file would remove the only third-party request.
- titris is left as it is.
