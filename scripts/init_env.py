#!/usr/bin/env python3
"""Create or complete the repository's `.env` from `.env.example`. Idempotent.

- Missing `.env`: copied from `.env.example`.
- Keys added to `.env.example` since: appended, with their example value.
- Secrets left empty: generated. Values already set are never changed, so running this again
  (or after pulling a newer `.env.example`) is always safe.

Standard library only: it runs before any dependency is installed.

    python3 scripts/init_env.py
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Generated when empty. Each one is used by the services as-is, so any random value works.
SECRETS = {
    "DJANGO_SECRET_KEY": lambda: secrets.token_urlsafe(50),
    "KEYCLOAK_ADMIN_PASSWORD": lambda: secrets.token_urlsafe(18),
    "OIDC_RP_CLIENT_SECRET": lambda: secrets.token_urlsafe(32),
}

# Required, but only a person can provide them.
MANUAL = ["LLM_API_KEY"]

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        match = _ASSIGNMENT.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2)
    return values


def init_env(example: Path, target: Path) -> list[str]:
    """Bring `target` up to date with `example`. Returns a log of the changes made."""
    log: list[str] = []
    example_lines = example.read_text().splitlines()
    if target.exists():
        lines = target.read_text().splitlines()
    else:
        lines = list(example_lines)
        log.append(f"created {target.name} from {example.name}")

    present = parse(lines)
    missing = [
        line
        for line in example_lines
        if (m := _ASSIGNMENT.match(line.strip())) and m.group(1) not in present
    ]
    if missing:
        lines += ["", f"# Added from {example.name} by scripts/init_env.py", *missing]
        log += [f"added {_ASSIGNMENT.match(line).group(1)}" for line in missing]

    for index, line in enumerate(lines):
        match = _ASSIGNMENT.match(line.strip())
        if match and match.group(1) in SECRETS and not match.group(2).strip():
            lines[index] = f"{match.group(1)}={SECRETS[match.group(1)]()}"
            log.append(f"generated {match.group(1)}")

    if log:
        target.write_text("\n".join(lines) + "\n")
        target.chmod(0o600)
    return log


def main() -> int:
    log = init_env(ROOT / ".env.example", ROOT / ".env")
    for entry in log:
        print(entry)
    if not log:
        print(".env is already complete; nothing changed.")
    if "generated KEYCLOAK_ADMIN_PASSWORD" in log:
        print(
            "Note: Keycloak reads KEYCLOAK_ADMIN_PASSWORD only on its very first start. If its "
            "database already existed, see 'Keycloak admin password' in docs/authentication.md."
        )
    values = parse((ROOT / ".env").read_text().splitlines())
    todo = [key for key in MANUAL if not values.get(key, "").strip()]
    if todo:
        print(f"Still to fill in by hand: {', '.join(todo)}.")
    print("Optional: social login (GOOGLE_*, MICROSOFT_*, APPLE_*) and SMTP_* credentials.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
