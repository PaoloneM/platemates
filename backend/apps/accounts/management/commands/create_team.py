from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.teams.models import Membership, Team


class Command(BaseCommand):
    help = (
        "Create a team owned by an existing user. Access is invitation-only, so this is how "
        "the first team (and its owner) comes to exist; the owner then invites everyone else. "
        "Idempotent: if that user already owns a team with that name, nothing is created."
    )

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument(
            "--owner", required=True, help="Email of a user who has signed in at least once."
        )
        parser.add_argument(
            "--staff", action="store_true", help="Also make the owner staff and superuser."
        )

    @transaction.atomic
    def handle(self, *args, name, owner, staff, **options):
        users = get_user_model().objects.filter(email__iexact=owner)
        if users.count() != 1:
            raise CommandError(
                f"Expected exactly one user with email {owner}, found {users.count()}. "
                "Sign in once through the app first."
            )
        user = users.get()
        team = Team.objects.filter(
            name=name,
            is_system=False,
            memberships__user=user,
            memberships__role=Membership.Role.OWNER,
        ).first()
        if team is None:
            team = Team.objects.create(name=name)
            Membership.objects.create(user=user, team=team, role=Membership.Role.OWNER)
            self.stdout.write(
                self.style.SUCCESS(f"Created team '{name}' (id {team.pk}), owner {owner}.")
            )
        else:
            self.stdout.write(f"Team '{name}' (id {team.pk}) already owned by {owner}.")
        if staff and not (user.is_staff and user.is_superuser):
            user.is_staff = user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])
            self.stdout.write(f"{owner} is now staff and superuser.")
