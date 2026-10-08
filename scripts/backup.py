#!/usr/bin/env python3
"""Back up and restore all persistent data: the application database and Keycloak's.

One backup is one `.tar` file under `backups/` (gitignored: it holds personal data and password
hashes), containing:

- `platemates.dump`, `keycloak.dump`: `pg_dump` custom-format dumps of both databases;
- `.env`: the configuration the data belongs with (Keycloak's admin password and the OIDC client
  secret must match what is in the Keycloak database);
- `manifest.json`: when, which databases, which git commit.

    python3 scripts/backup.py create [--keep N]   # new backup; optionally keep only the N newest
    python3 scripts/backup.py list
    python3 scripts/backup.py restore FILE [--yes]

`restore` replaces both databases with the backup's content. It first takes a safety backup of
the current state, stops the services that use the databases, and restarts the stack at the end.
It is repeatable: restoring the same file twice gives the same result. The backup's `.env` is
written to `.env` only if there is none (a new machine); otherwise it is saved next to it as
`.env.from-backup` for comparison.

Standard library only; needs the `db` service running (`docker compose up -d db`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "backups"
# Services that hold connections to the databases and must be stopped during a restore.
DB_CLIENTS = ["backend", "worker", "realtime", "embed-recipes", "keycloak", "keycloak-setup"]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip()
    return values


def databases(env: dict[str, str]) -> dict[str, str]:
    """Archive member name -> database name."""
    return {
        "platemates.dump": env.get("POSTGRES_DB") or "platemates",
        "keycloak.dump": env.get("KEYCLOAK_DB") or "keycloak",
    }


# Backups taken before the rename to PlateMates (2026-10-08) name the application dump so.
LEGACY_MEMBERS = {"platemates.dump": "mymenu.dump"}


def compose(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, **kwargs)


def db_exec(env: dict[str, str], *command: str, **kwargs) -> subprocess.CompletedProcess:
    user = env.get("POSTGRES_USER") or "platemates"
    return compose("exec", "-T", "db", *command, "-U", user, **kwargs)


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return result.stdout.strip() or "unknown"


# -- archive format (pure, tested) -----------------------------------------------------------


def write_archive(
    target: Path, dumps: dict[str, Path], env_file: Path | None, manifest: dict
) -> None:
    with tarfile.open(target, "w") as tar:
        data = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for name, path in dumps.items():
            tar.add(path, arcname=name)
        if env_file is not None and env_file.exists():
            tar.add(env_file, arcname=".env")
    target.chmod(0o600)


def read_manifest(archive: Path) -> dict:
    with tarfile.open(archive) as tar:
        try:
            member = tar.extractfile("manifest.json")
        except KeyError:
            member = None
        if member is None:
            raise ValueError(f"{archive.name} has no manifest: not a backup made by this script.")
        return json.load(member)


def backups_to_prune(existing: list[Path], keep: int) -> list[Path]:
    """The oldest backups beyond the `keep` newest. Names sort chronologically."""
    return sorted(existing)[:-keep] if keep > 0 else []


# -- commands --------------------------------------------------------------------------------


def create(keep: int | None = None, label: str = "") -> Path:
    env = read_env(ROOT / ".env")
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"platemates-{stamp}{('-' + label) if label else ''}.tar"

    with tempfile.TemporaryDirectory() as tmp:
        dumps: dict[str, Path] = {}
        for member, database in databases(env).items():
            path = Path(tmp) / member
            with path.open("wb") as out:
                db_exec(env, "pg_dump", "--format=custom", "--dbname", database, stdout=out)
            dumps[member] = path
        manifest = {
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "databases": {member: database for member, database in databases(env).items()},
            "git_commit": git_commit(),
        }
        write_archive(target, dumps, ROOT / ".env", manifest)

    size = target.stat().st_size / 1024
    print(f"created {target.relative_to(ROOT)} ({size:.0f} KiB)")
    if keep:
        for old in backups_to_prune(list(BACKUP_DIR.glob("platemates-*.tar")), keep):
            old.unlink()
            print(f"removed old backup {old.name}")
    return target


def list_backups() -> None:
    backups = sorted(BACKUP_DIR.glob("platemates-*.tar")) if BACKUP_DIR.exists() else []
    if not backups:
        print("no backups yet")
    for path in backups:
        manifest = read_manifest(path)
        size = path.stat().st_size / 1024
        print(f"{path.name}  {manifest['created_at']}  {size:.0f} KiB  git {manifest['git_commit']}")


def restore(archive: Path, assume_yes: bool) -> None:
    archive = archive.resolve()
    manifest = read_manifest(archive)
    env = read_env(ROOT / ".env")
    print(f"Restoring {archive.name} (taken {manifest['created_at']}).")
    print("This REPLACES all application data and all Keycloak accounts with the backup's.")
    if not assume_yes and input("Type 'restore' to continue: ").strip() != "restore":
        print("aborted")
        return

    safety = create(label="before-restore")
    print(f"safety backup of the current state: {safety.name}")

    compose("stop", *DB_CLIENTS)
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive) as tar:
        tar.extractall(tmp, filter="data")
        for member, legacy in LEGACY_MEMBERS.items():
            if not (Path(tmp) / member).exists() and (Path(tmp) / legacy).exists():
                (Path(tmp) / legacy).rename(Path(tmp) / member)
        for member, database in databases(env).items():
            if not (Path(tmp) / member).exists():
                raise ValueError(f"{archive.name} lacks {member}")
        for member, database in databases(env).items():
            db_exec(env, "dropdb", "--if-exists", "--force", database)
            db_exec(env, "createdb", database)
            with (Path(tmp) / member).open("rb") as dump:
                db_exec(env, "pg_restore", "--exit-on-error", "--no-owner", "--dbname",
                        database, stdin=dump)
            print(f"restored database {database}")

        backup_env = Path(tmp) / ".env"
        if backup_env.exists():
            if not (ROOT / ".env").exists():
                (ROOT / ".env").write_bytes(backup_env.read_bytes())
                (ROOT / ".env").chmod(0o600)
                print("restored .env from the backup")
            elif backup_env.read_bytes() != (ROOT / ".env").read_bytes():
                (ROOT / ".env.from-backup").write_bytes(backup_env.read_bytes())
                (ROOT / ".env.from-backup").chmod(0o600)
                print(
                    "kept the current .env; the backup's differs and was saved as "
                    ".env.from-backup. KEYCLOAK_ADMIN_PASSWORD and OIDC_RP_CLIENT_SECRET must "
                    "match the restored data: compare the two files."
                )

    compose("up", "-d")
    print("done; the stack is starting again")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create_cmd = sub.add_parser("create", help="take a new backup")
    create_cmd.add_argument("--keep", type=int, help="keep only the N newest backups")
    sub.add_parser("list", help="list backups")
    restore_cmd = sub.add_parser("restore", help="replace all data with a backup")
    restore_cmd.add_argument("file", type=Path)
    restore_cmd.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    try:
        if args.command == "create":
            create(keep=args.keep)
        elif args.command == "list":
            list_backups()
        else:
            restore(args.file, args.yes)
    except subprocess.CalledProcessError as exc:
        print(f"failed: {' '.join(exc.cmd)} exited with {exc.returncode}", file=sys.stderr)
        return 1
    except (ValueError, OSError, tarfile.TarError) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
