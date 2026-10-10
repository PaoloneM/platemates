import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.transfer.importing import MODES, TransferError, import_document

from .export_data import find_team


class Command(BaseCommand):
    help = (
        "Import a PlateMates export file. Idempotent: importing it again changes nothing "
        "(with --mode update, it re-applies the file's values)."
    )

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--mode", choices=MODES, default="skip")
        parser.add_argument("--team", help="import the file's team into this one (id or name)")
        parser.add_argument("--owner", help="email of the owner of a team created by the import")
        parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")

    def handle(self, file, mode, team, owner, dry_run, **options):
        try:
            document = json.loads(Path(file).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Cannot read {file}: {exc}") from exc
        users = get_user_model().objects
        user = users.filter(email=owner).first() if owner else users.filter(is_staff=True).first()
        if user is None:
            raise CommandError("No owner for new teams: pass --owner <email> of an existing user.")
        try:
            report = import_document(
                document,
                user=user,
                mode=mode,
                target_team=find_team(team) if team else None,
                dry_run=dry_run,
            )
        except TransferError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report.as_dict(), ensure_ascii=False, indent=1))
