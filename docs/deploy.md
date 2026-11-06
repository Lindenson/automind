# Deploying and moving AutoMind

AutoMind runs as one Docker Compose project: Postgres 16 and the app, plus two optional profiles —
`monitoring` (Prometheus + Alertmanager) and `public` (Caddy with automatic HTTPS). Everything goes through
`scripts/deploy.sh`; `scripts/deploy.sh help` lists the commands.

## What lives where

| What | Where | In git | In a bundle |
|---|---|---|---|
| Code, compose file, Dockerfile | the clone | yes | the commit id only |
| API keys | `.env` | no | yes |
| `POSTGRES_PASSWORD`, `ADMIN_TOKEN`, `METRICS_TOKEN`, port settings | `.env.docker` (generated) | no | yes |
| Database (chats, issues, source registry, ...) | volume `<project>_pgdata` | no | fresh `pg_dump` |
| Prometheus token file | `deploy/prometheus/metrics_token` (mode 600, from `METRICS_TOKEN`) | no | yes |
| Alert rules, Prometheus/Alertmanager config, Caddyfile | `deploy/` | yes | yes (your local receiver settings travel too) |
| Prometheus history (400 days) | volume `<project>_promdata` | no | no (starts fresh on the new host) |

A bundle holds every secret of the installation. It is written with mode 600; keep it off shared disks, or use
`--encrypt` (`age -p` or `gpg -c`, whichever is installed).

## A new server

```bash
git clone <origin> ~/automind && cd ~/automind
scripts/deploy.sh bootstrap        # checks Docker, the compose plugin and git; prints the install commands if
                                   # something is missing (it never runs sudo); creates .env interactively
scripts/deploy.sh up --monitoring  # app on 127.0.0.1:8080, Prometheus 127.0.0.1:9090, Alertmanager 127.0.0.1:9093
```

On Ubuntu/Debian the missing pieces are, as `bootstrap` prints them:

```bash
sudo apt-get update && sudo apt-get install -y git curl ca-certificates
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # then log out and in again
```

## Moving to another server

### One command (SSH)

```bash
scripts/deploy.sh move user@new-host            # into ~/automind on the target; or: move user@new-host /srv/automind
```

It checks that the current commit is on `origin` (push first), that the target has Docker, the compose plugin, git
and curl (otherwise it prints the install commands and stops), clones `origin` at the same commit, makes a fresh
bundle here, copies it with `scp`, runs `scripts/deploy.sh import` there and deletes the copied bundle after a
successful import. For a private repository the target needs read access (a deploy key), or set
`AUTOMIND_MOVE_ORIGIN=https://...`. **The old stack keeps running**: there is no silent cut-over.

### By hand (any transport)

```bash
# old host
scripts/deploy.sh export                        # -> backups/automind-bundle-<time>.tar.gz (mode 600)
scp backups/automind-bundle-*.tar.gz user@new-host:

# new host (fresh clone, no .env yet)
git clone <origin> ~/automind && cd ~/automind
scripts/deploy.sh import ~/automind-bundle-<time>.tar.gz --monitoring
```

`import` checks out the bundle's commit (fetching it from `origin` when needed; it stops if the working tree has
local changes), restores `.env`, `.env.docker` and the metrics token, builds the image, starts Postgres, restores the
dump, starts the app and waits until it is healthy. It refuses to overwrite an existing `.env`/`.env.docker` or a
non-empty database unless you pass `--force`.

### Verify on the new host

```bash
scripts/deploy.sh status                                         # containers + "health: ok"
curl -s http://127.0.0.1:8080/api/v1/health                      # 200, keys present
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(sed -n 's/^METRICS_TOKEN=//p' .env.docker)" http://127.0.0.1:8080/metrics   # 200
scripts/deploy.sh monitoring status                              # scrape automind ... -> up, rules loaded: 16
```

Open `http://127.0.0.1:8080/admin` (through `ssh -L 8080:127.0.0.1:8080 user@new-host` when the app is bound to
127.0.0.1), log in with `ADMIN_TOKEN` from `.env.docker`, and check that the top problems and the source registry
look like on the old host; open a few chats.

### Retire the old host

Only after the checks above:

```bash
scripts/deploy.sh down        # on the OLD host: stops it, keeps its volumes as a fallback
# later, when you are sure: scripts/deploy.sh destroy   (deletes the old database volume)
```

Chats written on the old host after the export are not in the bundle. Stop using the old host before the final
`export`/`move`, or repeat the move.

## Monitoring

`scripts/deploy.sh monitoring up` writes `deploy/prometheus/metrics_token` from `METRICS_TOKEN` (mode 600,
gitignored) and starts Prometheus (`prom/prometheus:v3.5.0`, 400 days of retention) and Alertmanager
(`prom/alertmanager:v0.28.1`), both on 127.0.0.1 only. Prometheus runs as your user id (so it can read the token
file) in group `nobody` (so it can write its data volume). Rules: `deploy/prometheus/automind-rules.yml`
(16 alerts, contracts in `specs/010-self-observing-registry/contracts/metrics.md`). Notifications: put a receiver
into `deploy/prometheus/alertmanager.yml` (Telegram, Slack or e-mail examples are in the file; the shipped one
delivers nowhere) and run `scripts/deploy.sh monitoring up` again.

## Public HTTPS

`AUTOMIND_DOMAIN=automind.example.com` in `.env.docker`, DNS pointing at the server, ports 80/443 open, then
`scripts/deploy.sh up --public`. Caddy obtains the certificate and proxies to the app; `/metrics` is not proxied.
AutoMind has no login yet: work through the security list in [review-2026-11-03.md](history/review-2026-11-03.md) first.

## Rehearsal (T087), 2026-11-05

A second compose project on the same host stood in for the new server, with its own ports, so the real stack
(project `automind`) was not touched:

```bash
export COMPOSE_PROJECT_NAME=automind-move AUTOMIND_PORT=8091 AUTOMIND_DB_PORT=5439 \
       AUTOMIND_PROMETHEUS_PORT=9190 AUTOMIND_ALERTMANAGER_PORT=9193
```

"Old host" and "new host" were two fresh clones of branch `010-ops` (commit `7b6ccc6`) in a temporary directory.
`.env` held dummy keys only (`GOOGLE_API_KEY=dummy`, `SERPER_API_KEY=dummy`); the app starts without calling the
providers.

| Step | Command | Result |
|---|---|---|
| 1 | old: `scripts/deploy.sh up --monitoring` | `.env.docker` generated; healthy on :8091; `/api/v1/health` 200, `/metrics` 200 with the token (38 `automind_` families) and 403 without it, `/admin` 200; Prometheus target `automind` **up**, 16 rules loaded, none firing |
| 2 | old: a marker row in a new table `rehearsal_marker` | data to recognise after the move |
| 3 | old: `scripts/deploy.sh export <file>` | 99 KB bundle, mode 600: `automind.sql.gz`, `env`, `env.docker`, `metrics_token`, `config/deploy/...`, `BUNDLE_INFO` (format, commit, date, host, origin, dirty=no) |
| 4 | old: `scripts/deploy.sh destroy` | project `automind-move` and its volumes gone |
| 5 | new: `scripts/deploy.sh import <file> --monitoring` | secrets restored (mode 600), image built, dump restored, app healthy; same probes as step 1, Prometheus target **up** |
| 6 | compare | identical row counts and marker: `issues=15 capabilities=487 sources=209 registry_changes=489 marker=made-on-old-host alembic=0016`; `.env`, `.env.docker`, `metrics_token` byte-identical |

Refusals checked as well: `import` again in the same clone stops because `.env` exists; `import` from a clone at an
older commit checks out the bundle's commit (`5565821` → `7b6ccc6`) and then stops because the database already has
51 tables (no `--force`); with an edited `README.md` it stops before the checkout ("the working tree has local
changes").

Not rehearsed:

- **`move` over SSH**: there was no second machine or SSH server for a real target. The parts it is built from
  (`export`, `import`, the clone at a commit) ran in the rehearsal above; the SSH/scp plumbing and the remote
  prerequisite checks did not.
- **Chats**: with dummy keys no chat can be answered, so the database had no chats (0 before and after). The
  registry, insight issues and the marker table travelled; chats are rows in the same dump.
- **`--encrypt`**: `age` was not installed; `gpg -c` needs a passphrase prompt, which the non-interactive run could
  not answer.
- **`--public`**: needs a domain with DNS and open ports 80/443; only `caddy validate` of the Caddyfile was run.
- **`bootstrap`** on an empty server: run only on this machine (Docker present).
