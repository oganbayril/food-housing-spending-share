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

## Phase C: rename `00-existing.conf` to `realestate.conf`

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

## Phase D: real-estate `setup.sh` stops overwriting the main Caddyfile

A separate commit in the **germany-real-estate-api** repo:
- `setup.sh` writes `/etc/caddy/sites-enabled/realestate.conf` instead of
  `/etc/caddy/Caddyfile`;
- it creates `/etc/caddy/Caddyfile` with `import sites-enabled/*` only if
  that file does not exist, so other projects' sites are never touched;
- `deploy/README.md` updated to match.

Tested locally, not on the VPS: generate the file to a temporary path with the
same `sed` and diff it against the live `realestate.conf`.

## Phase E: add this site

1. Files, from the local machine, after `uv run python src/build_map.py`:

   ```bash
   ssh root@89.167.25.74 "mkdir -p /srv/food-housing-share && chmod 755 /srv/food-housing-share"
   scp site/index.html site/shares.csv root@89.167.25.74:/srv/food-housing-share/
   ssh root@89.167.25.74 "chmod 644 /srv/food-housing-share/*"
   scp deploy/food-housing.caddy root@89.167.25.74:/root/food-housing.caddy
   ```

2. **Before the reload:** check the response headers in
   `deploy/food-housing.caddy` against what the page needs: its inline
   scripts (Plotly and the page script) and the runtime fetch of the map
   outlines from Plotly's CDN. A Content-Security-Policy, if added, must
   allow both, and must be tested in a browser.
3. Site config, on the server:

   ```bash
   sed "s/FOODHOUSING_DOMAIN/food-housing-spending-share.duckdns.org/" /root/food-housing.caddy \
     > /etc/caddy/sites-enabled/food-housing.conf
   caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   systemctl reload caddy
   ```

   `food-housing.conf` sorts first alphabetically; each file is a different
   domain, so order does not matter.

4. Test:

   ```bash
   curl -sI https://food-housing-spending-share.duckdns.org/ | head -5        # 200, text/html, HSTS
   curl -sI https://food-housing-spending-share.duckdns.org/shares.csv | grep -i disposition
   curl -s -o /dev/null -w "%{http_code}\n" https://germany-real-estate.duckdns.org/health
   curl -s -o /dev/null -w "%{http_code}\n" https://titris.duckdns.org/
   ```

   Then in a browser: map loads, slider, hover, dark mode, World / Europe
   zoom, CSV download.

Rollback: `rm /etc/caddy/sites-enabled/food-housing.conf && systemctl reload caddy`.

## Updating the site later

The data changes about once a year. Rebuild locally and copy the two files;
no Caddy reload is needed for static files:

```bash
uv run python src/build_map.py
scp site/index.html site/shares.csv root@89.167.25.74:/srv/food-housing-share/
```

## Known follow-ups (not blocking)

- The page loads the map outlines (`world_50m.json`) from Plotly's CDN at
  view time. Self-hosting that file would remove the only third-party request.
- titris is left as it is.
