# Operations: data, backups, moving the stack

## Where the data lives

All persistent data is in one Docker volume, `mymenu_pgdata`: the PostgreSQL server holding both
the application database (`mymenu`: families, recipes, menus) and Keycloak's (`keycloak`:
accounts, passwords, links to Google/Microsoft/Apple). The volume name is stable because
`docker-compose.yml` fixes the project name (`name: mymenu`). `mymenu_hf-cache` only caches the
embedding model and can always be re-downloaded.

| Command | Data |
|---|---|
| `docker compose stop` / `down` / `up --build` | kept |
| `docker compose down -v` | **deleted**: `-v` removes the volumes, accounts included |
| `docker volume rm mymenu_pgdata`, `docker system prune --volumes` | **deleted** |

After a deletion the stack still starts (every initialization step is repeatable), but empty:
everyone must register again. Restore a backup instead.

## Backups

```bash
python3 scripts/backup.py create            # new backup in backups/
python3 scripts/backup.py create --keep 14  # ... and keep only the 14 newest
python3 scripts/backup.py list
python3 scripts/backup.py restore backups/mymenu-20261006-082439.tar
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
