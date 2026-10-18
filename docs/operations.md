# Operations: data, backups, moving the stack

## Where the data lives

All persistent data is in one Docker volume, `platemates_pgdata`: the PostgreSQL server holding both
the application database (`platemates`: teams, recipes, menus) and Keycloak's (`keycloak`:
accounts, passwords, links to Google/Microsoft/Apple). The volume name is stable because
`docker-compose.yml` fixes the project name (`name: platemates`). `platemates_hf-cache` only caches the
embedding model and can always be re-downloaded. Redis holds only a cache, in memory, with no
volume: restarting it loses nothing.

| Command | Data |
|---|---|
| `docker compose stop` / `down` / `up --build` | kept |
| `docker compose down -v` | **deleted**: `-v` removes the volumes, accounts included |
| `docker volume rm platemates_pgdata`, `docker system prune --volumes` | **deleted** |

After a deletion the stack still starts (every initialization step is repeatable), but empty:
everyone must register again. Restore a backup instead.

## The language model

The chat model runs in Unsloth Studio on the host, outside the stack. Its context window is set
when the model is loaded: in Studio's model settings (context length), or through its API:

```bash
curl -X POST http://127.0.0.1:8888/api/inference/load -H "Authorization: Bearer $LLM_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model_path": "unsloth/Qwen3.6-35B-A3B-MTP-GGUF", "gguf_variant": "UD-Q4_K_XL",
       "max_seq_length": 65536}'
```

Left at 0, Studio picks 8192. Qwen3.6-35B-A3B has a light context cache: at 64k it needs
about 28.5 GB against 27.1 GB at 8k (Studio's `/api/inference/estimate-memory`, 2026-10-08),
and it read a 36k-token prompt correctly in 34 s. Loading it again takes about 16 s and
interrupts what Studio is doing for other programs.

Then tell the app, from Management > Settings (administrators only): **Model context** must
match the loaded context, never exceed it; prompt budgets follow it. **Model reasoning**
(thinking) for menu generation needs at least 32k.

## Backups

```bash
python3 scripts/backup.py create            # new backup in backups/
python3 scripts/backup.py create --keep 14  # ... and keep only the 14 newest
python3 scripts/backup.py list
python3 scripts/backup.py restore backups/platemates-20261006-082439.tar
```

A backup is one `.tar` file holding `pg_dump` dumps of both databases, the `.env` the data belongs
with, and a manifest (date, git commit). `backups/` is gitignored: backups contain personal data
and password hashes. Keep a copy off the machine too (an external disk, a private cloud folder):
a backup on the same disk does not survive the disk.

`restore`:

1. asks for confirmation (`--yes` skips it);
2. takes a safety backup of the current state (`...-before-restore.tar`);
3. stops the services using the databases, drops and recreates both databases from the backup;
4. starts the stack again.

Restoring the same file twice gives the same result. The script needs only the `db` service
running and Python's standard library.

To back up automatically, schedule `create --keep N` (cron on Linux/Raspberry Pi, launchd on
macOS), from the repository root.

## Using the app from a phone

The Mac publishes the app on `http://localhost:8080` for itself only. Phones and tablets on the
home network need HTTPS (Keycloak's login cookies require it outside localhost):

```bash
python3 scripts/setup_lan_https.py     # idempotent; needs `brew install mkcert`
# The services that read the allowed addresses from .env (backend, realtime, keycloak-setup)
# must be recreated to see them; Traefik reloads the certificate by itself.
docker compose up -d --force-recreate backend realtime keycloak-setup
```

The script creates a certificate authority for this project (`secrets/tls/ca`, gitignored, not
added to the Mac's keychain), a certificate for the Mac's `<name>.local` and LAN IP, and the
Traefik configuration that serves it on port 8443 (`secrets/tls/tls.yml`); it adds those
addresses to `.env`. Until it has run, port 8443 answers with Traefik's own self-signed
certificate.

On each phone or tablet, once, trust `secrets/tls/platemates-local-ca.crt` (AirDrop it or email it):

- **iPhone/iPad**: open it, then Settings > General > VPN & Device Management > install the
  profile; then Settings > General > About > Certificate Trust Settings > enable full trust.
- **Android**: Settings > Security > Encryption & credentials > Install a certificate > CA
  certificate.

Then open `https://<name>.local:8443` (or `https://<LAN IP>:8443`). The camera button of the
recipe assistant opens the phone's camera directly.

If the Mac's IP changes (DHCP, or another network interface: on 2026-10-08 it moved from Wi-Fi's
`.209` to a cable's `.219`), re-run the script and recreate the containers: the certificate is
reissued, the authority stays the same, so phones need nothing new. `<name>.local` keeps
working across IP changes, so prefer it on the phones.

If port 8443 answers with "TRAEFIK DEFAULT CERT", Traefik cannot see `secrets/tls`: a container
created before the repository folder was moved or renamed still mounts the old path, and
`restart` keeps it. Recreate it: `docker compose up -d --force-recreate traefik`. Whoever has
`secrets/tls/ca/rootCA-key.pem` can issue certificates your devices will trust: never share it,
only the `.crt`.

## Exposing the app beyond the home network

Traefik discovers containers through the Docker socket, mounted read-only. Read access to the
Docker API still reveals every container's configuration, environment variables included. That
is acceptable on a home machine; on a server exposed to the internet, `docker-compose.prod.yml`
puts a socket proxy in between (`tecnativa/docker-socket-proxy`, listing containers only).

## The public server (platemates.cloud)

A Hetzner Cloud VM (`platemates01`, CX23, Ubuntu 26.04) runs the stack from published images:

- **Images**: GitHub Actions (`.github/workflows/images.yml`) runs the backend tests and the
  frontend checks on every push, then builds the backend, frontend, Keycloak and embeddings
  images and publishes them to `ghcr.io/paolonem/platemates-*`, tagged `sha-<commit>`, `main`
  and `latest`. The packages must be public (GitHub → Packages → each one → Package settings →
  visibility) for the server to pull them without a token.
- **Compose**: `docker-compose.prod.yml` on top of the base file (the server's `.env` sets
  `COMPOSE_FILE`, so plain `docker compose` uses both): registry images at
  `PLATEMATES_VERSION`, ports 80 and 443 only, HTTP redirected to HTTPS, a Let's Encrypt
  certificate for `PLATEMATES_DOMAIN`, the socket proxy, restart after a reboot.
- **Deploy**: `scripts/deploy.sh` runs Ansible (`deploy/`) in the `authkeys/docker-ansible`
  container, with the Mac's ssh-agent and the host key pinned in `deploy/known_hosts`. Roles:
  `base` (updates, automatic security updates, keys-only SSH, ufw allowing 22/80/443,
  fail2ban, swap), `docker` (`geerlingguy.docker`, rotated logs), `platemates` (checkout of
  the repository, `.env`, pull and `up`, wait for `/api/health/`). Idempotent: run it again to
  deploy a new version; `--tags app` for the app only, `-e platemates_version=sha-<commit>` to
  pin a build, `--check --diff` to see what would change.
- **Secrets**: the server's `.env` is created once by `scripts/init_env.py` on the server
  (Django key, Keycloak passwords) plus a random database password on the first deploy; they
  never leave the server and are never overwritten. Ansible sets only the non-secret values
  (domain, URLs, `DJANGO_DEBUG=false`, secure cookies). Personal values (the Let's Encrypt and
  administrator emails) are in `deploy/group_vars/platemates/vault.yml`, encrypted with
  ansible-vault; the password is in `~/.config/platemates/ansible-vault-password`, outside the
  repository (keep a copy in a password manager). `scripts/deploy.sh vault edit` changes them.
- **Models**: Claude answers and OpenAI embeds (`LLM_PROVIDER=anthropic`,
  `EMBEDDINGS_PROVIDER=openai`); their API keys are in the vault (`vault_anthropic_api_key`,
  `vault_openai_api_key`) and written into the server's `.env`. Spending limits are set in each
  provider's console.
- **Backups**: see "Backups of the public server" below.
- **DNS and firewall**: `platemates.cloud` needs an A record to the VM's address, and the
  Hetzner Cloud firewall attached to the VM must let in TCP 80 and 443 (besides 22), or Let's
  Encrypt cannot reach the server and Traefik serves its default certificate. Traefik asks for
  the certificate from the frontend's router (`docker-compose.prod.yml`): the base file's routers
  set `tls=true` themselves, which makes Traefik ignore a resolver set on the entry point. After
  fixing either, `docker compose restart traefik` on the server asks again at once.

## Cloudflare (decided with Paolo 2026-10-18)

Cloudflare is in front of everything: its DNS (the domain stays registered at Hostinger), its
proxy, and a tunnel through which the traffic reaches the server, so that no web port needs to
be open. Configured through its API only, by `deploy/roles/cloudflare`
(`files/cloudflare_setup.py`, idempotent and convergent, like `setup_keycloak`):

- **Zone**: SSL Full (strict), HTTPS only, TLS 1.2 at least, WebSockets (Socket.IO).
- **Tunnel** `platemates`: `cloudflared` (compose profile `cloudflare`, its token written into
  `.env` by the deploy) opens an outbound connection; each host goes to its Traefik over TLS
  inside the compose network (`platemates.cloud` and `www` to `traefik`, `admin` to
  `traefik-admin`).
- **Access** on the admin host: Google (an OAuth client of its own, redirect
  `https://platemates.cloudflareaccess.com/cdn-cgi/access/callback`) or a one-time code by
  email; allowed: `APP_ADMINS`; 24 h sessions. Created before any DNS change. mTLS was left
  out: on the Free plan it can only be a WAF rule that blocks every request without a
  certificate, which would shut out phones and Telegram's browser.
- **Rate limit** on `/api/request-invite/` (the Free plan's one rule), on top of the app's own.
- **The client's address**: Traefik sees cloudflared's; the app reads `CF-Connecting-IP`.
- **Credentials** (vault): `vault_cloudflare_api_token` (deploy: tunnel, Access, DNS, WAF,
  zone settings; used from the control node only), `vault_cloudflare_account_id`,
  `vault_cloudflare_google_client_id`/`_secret`, `vault_cloudflare_dns_token` (on the server,
  for the certificates: DNS of this zone only).
- **Steps** (`deploy/group_vars/platemates/main.yml`), each a deploy, each undone by one:
  `cloudflare_enabled: true` once the zone is active; hosts added to `cloudflare_tunnel_hosts`
  one at a time (admin first; taking a host out gives it back its direct record); last,
  `platemates_public_ports_open: false` (Traefik's 80 and 443 only on 127.0.0.1, closed in ufw).
- Mail (ImprovMX's MX and SPF records) is never touched.

## The admin plane

Everything that is not the app is served only on the VM's loopback (decided with Paolo
2026-10-11): Gestione, Django admin, Keycloak's admin console, and the monitoring.

- **How to get there**: `https://admin.platemates.cloud`, from anywhere, phone included, once
  the admin host is in Cloudflare's tunnel (below): Cloudflare Access asks for a Google login or
  a one-time code sent by email, and lets in only the app's administrators (`APP_ADMINS`);
  then the app's own sign-in as usual (a separate session from the public site's: cookies are
  per host). **The way in when Cloudflare is not**: `ssh -N platemates-admin` (in
  `~/.ssh/config.d/platemates`, it forwards local 9443 to the VM's 127.0.0.1:9443), with
  `127.0.0.1 admin.platemates.cloud` in the Mac's `/etc/hosts` once the public name points to
  Cloudflare, then `https://admin.platemates.cloud:9443`.
- **How it works**: a second Traefik, `traefik-admin` (`docker-compose.prod.yml`), publishes only
  `127.0.0.1:9443`; its routes are a file (`traefik-admin/dynamic.yml`), it has no Docker access.
  Cloudflare's tunnel reaches it from inside the compose network. Its certificate, like the
  public Traefik's, is Let's Encrypt's through a DNS challenge on Cloudflare
  (`vault_cloudflare_dns_token`: a token that edits this zone's DNS only).
- **Planes in the backend** (`apps/core/planes.py`): each Traefik sets `X-PlateMates-Plane`
  (`public` or `admin`), overwriting what the client sent; staff and admin powers exist only
  with `admin`. On the public plane a staff account is an ordinary user, Gestione does not
  appear, and Django admin and the admin-only APIs answer 404 (and are not routed either).
  Without the header (`DEFAULT_PLANE`): `public` on the server, `admin` on a developer's machine.
- **Monitoring** (on the admin plane only): VictoriaMetrics (30 days) collects the VM
  (node-exporter, with textfile metrics written on the host: the backups' outcome from
  `platemates-backup`, and each container's CPU and memory read from its cgroup by
  `platemates-container-metrics` every 30 s; cAdvisor was dropped, as it now needs containerd's
  socket, i.e. control of the machine), PostgreSQL and WAL archiving (postgres-exporter, role
  `monitoring`), both Traefiks (requests, errors and latency per service) and Keycloak
  (`monitoring/scrape.yml`). Grafana, at `/grafana`, is embedded in the app's Monitoring page
  (user menu, administrators, admin host only); it signs in through Keycloak (client
  `platemates-grafana`, administrators only) and reads the AI usage from PostgreSQL as
  `grafana_reader` (usage, prices, team names, and the invite requests' dates and status only;
  `monitoring/db-roles.sql`). Dashboards
  are code: `python3 monitoring/grafana/make_dashboards.py`, never edited in Grafana.
  **Alerts** go to Telegram (bot token and chat id in the vault), defined as code in
  `monitoring/grafana/make_alerts.py`: backup older than 26 h, WAL archiving failing,
  PostgreSQL down, disk over 85%, memory under 10%, a monitored service down, 5xx on the public
  site, AI spending over a daily threshold, invite requests waiting. Each is sent when it fires
  and when it resolves, repeated every 12 h while it lasts, as a short Italian message (the
  template `platemates.telegram` in the same file: an icon by severity, the title, what is wrong
  with the measured value, what to do, a link to the page of the app to look at (Manage or
  Monitoring, `ADMIN_URL`); "Risolto" when it ends). Test a template change
  in a throwaway Grafana of the same version and its
  `/api/alertmanager/grafana/config/api/v1/templates/test` before deploying: a provisioning
  error stops every alert. They run on the VM itself: if the VM is down nothing is
  sent, which only an external check of `https://platemates.cloud/api/health/` (UptimeRobot,
  also able to write to Telegram) can catch.
- **Social login on the admin host**: Keycloak builds each provider's redirect URI from the
  address it is reached at, so every address needs its own registered with the provider, e.g.
  Google: `https://admin.platemates.cloud:9443/auth/realms/platemates/broker/google/endpoint`
  besides `https://platemates.cloud/auth/realms/platemates/broker/google/endpoint`.
- **Denied on the public plane**: `/manage`, `/admin/`, `/api/config|cache|usage|transfer|system-drafts`,
  Keycloak's `/auth/admin` and the `master` realm (its login page is Keycloak's own
  administrators').

## Backups of the public server

pgBackRest (decided with Paolo 2026-10-10), in the database image `platemates-db`
(`db/Dockerfile`), backs up the whole PostgreSQL cluster: the app's database and Keycloak's.

- **What runs**: PostgreSQL archives its WAL continuously into the repository
  (`archive_timeout=300`: never more than 5 minutes behind). The `platemates-backup` systemd
  timer (`deploy/roles/backup`) takes a differential backup every night at 03:30 and a full one
  on Sundays, runs `pgbackrest check`, and writes an encrypted copy of the server's `.env`.
  Retention: two full backups, so any moment of about the last two weeks can be restored.
- **Where**: `/var/backups/platemates/pgbackrest` (the repository, AES-256 encrypted, zstd) and
  `/var/backups/platemates/env/platemates.env.enc`. The passphrase is `vault_pgbackrest_cipher_pass`
  in the vault: **without it the backups cannot be read**. Keep a copy in a password manager,
  with the vault password.
- **Copy at home**: the home NAS pulls `/var/backups/platemates` with rsync over SSH, as the
  `nasbackup` user, whose key (`backup_pull_keys` in `deploy/group_vars/platemates/main.yml`)
  can only run a read-only rsync of that folder (`rrsync -ro`). The home connection starts the
  transfer, so home needs no fixed address. Files in the repository never change once written,
  so each run moves only what is new. The target is a folder of its own, never the copying
  user's home: `--delete` makes it match the server, and would delete the user's SSH key along
  with everything else (happened once, 2026-10-10). Run it every few hours, with `--delete` to follow the
  retention, and keep ZFS snapshots of the target dataset so a deletion on the server cannot
  erase the copies. `rrsync -ro` refuses `--remove-source-files` and any write. The copy needs
  GNU rsync (FreeNAS/TrueNAS, Linux): macOS's openrsync sends `--delete` to the server even
  when pulling, and `rrsync -ro` refuses it. Verified 2026-10-10: a first pull of 2348 files
  (7.7 MB), a second one transferring nothing.
- **The home FreeNAS (11.3)**, set up 2026-10-10: user `platemates`, an rsync task (Pull, SSH,
  `nasbackup@2.29.107.140`, remote path `/`, every 2 hours at :15, Delete on) into
  `/mnt/RaidoZzo/paoloBkup/platemates/server`, with `--filter='P .ssh/'` as an extra option.
  Learned the hard way: FreeNAS 11.3 cannot read ed25519 keys when it saves the task (use
  RSA); "Validate Remote Path" must be off, since it runs a shell command rrsync refuses; and
  the task's path must not be the user's home, which `--delete` emptied twice, keys included.
- **State**: `systemctl list-timers platemates-backup.timer`, `journalctl -u platemates-backup`,
  `docker compose exec -u postgres db pgbackrest --stanza=platemates info`.

Restore, on the server (or a new one deployed with `scripts/deploy.sh`, the repository copied
back from the NAS into `/var/backups/platemates`):

```bash
cd /opt/platemates
docker compose stop                     # everything: nothing may use the database
# Latest state (end of the archived WAL); or a moment: --type=time "--target=2026-10-10 12:00:00+02"
docker compose run --rm --no-deps -u postgres db \
  pgbackrest --stanza=platemates --delta restore
docker compose up -d
```

`--delta` rewrites only what differs in the existing data volume. On a new machine, first
decrypt the `.env` (its database password must match the restored roles):
`openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:<passphrase> -in platemates.env.enc -out .env`.

## Moving to another machine

1. On the old machine: `python3 scripts/backup.py create`.
2. On the new one: clone the repository, copy the backup into `backups/`, **do not** create
   `.env` yet.
3. `docker compose up -d db`, then `python3 scripts/backup.py restore backups/<file>.tar`. With no
   `.env` present, the backup's is restored too, so Keycloak's admin password and the OIDC client
   secret match the restored data.
4. Adapt `.env` to the new host (URLs, `LLM_BASE_URL`; see "HTTP, HTTPS and other hosts" in
   `docs/authentication.md`), then `docker compose up -d`.

If a `.env` already exists on the target, `restore` keeps it and writes the backup's next to it as
`.env.from-backup`. `KEYCLOAK_ADMIN_PASSWORD` and `OIDC_RP_CLIENT_SECRET` must then be taken from
the backup's file: `setup_keycloak` rewrites the client secret from `.env` anyway, but the admin
password lives in Keycloak's database (see "Keycloak admin password" in
`docs/authentication.md`).
