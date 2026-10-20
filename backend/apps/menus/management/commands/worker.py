"""Run the background work, one task at a time, until stopped: menu generations
(`apps.menus.generation`) and system recipe drafts (`apps.curation.jobs`).

`docker compose` runs it as the `worker` service; in native development run it beside
`runserver`. One worker is enough: both kinds of task wait for the LLM, which serves one request
at a time anyway. Menu generations go first, since a user is waiting for them: after every task
the worker looks at them before taking the next draft. On start, tasks a previous worker left
running are marked failed.

The queues are the `MenuGeneration` and `SystemDraft` tables. The worker sleeps in PostgreSQL's
`LISTEN` and is woken by the `NOTIFY` the API sends when it queues a task, so it starts at once
and asks the database nothing while idle. A notification is not stored: one sent while the
worker was down or reconnecting is lost, so the worker also looks at the queues every
SAFETY_CHECK_SECONDS, and always when it starts.
"""

import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError, connection

from ai import get_chat_provider
from apps.curation import campaigns
from apps.curation import jobs as drafts
from apps.menus import generation as menus
from apps.teams.models import Team
from apps.transfer import jobs as imports
from apps.usage.context import attribute
from apps.usage.models import Feature

log = logging.getLogger(__name__)

# The safety net for lost notifications: one query a minute while idle.
SAFETY_CHECK_SECONDS = 60
# How often a wait looks at the stop flag. Local: no query is sent.
STOP_CHECK_SECONDS = 1
RECONNECT_SECONDS = 5


CHANNELS = (menus.CHANNEL, drafts.CHANNEL, imports.CHANNEL)


def listen() -> None:
    """Subscribe this process's database connection to the channels. Harmless if already
    subscribed; needed again after a reconnection."""
    with connection.cursor() as cursor:
        for channel in CHANNELS:
            cursor.execute(f"LISTEN {channel}")


def wait_for_notification(seconds: float, stopping=lambda: False) -> bool:
    """Wait until a notification arrives (True), the time is up or the worker stops (False)."""
    raw = connection.connection
    deadline = time.monotonic() + seconds
    while not stopping():
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        for _ in raw.notifies(timeout=min(STOP_CHECK_SECONDS, left), stop_after=1):
            return True
    return False


class Command(BaseCommand):
    help = "Run queued menu generations and system recipe drafts in the background."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run what is queued, then exit.")

    def handle(self, *args, once=False, **options):
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        if interrupted := (
            menus.fail_interrupted() + drafts.fail_interrupted() + imports.fail_interrupted()
        ):
            self.stdout.write(f"Marked {interrupted} interrupted task(s) as failed.")
        self.stdout.write("Worker started.")
        while not stopping:
            try:
                # Listen before looking at the queue: a generation queued in between is then
                # both in the queue and announced, never missed.
                listen()
                while not stopping and self._run_next(lambda: stopping):
                    pass
                if once:
                    break
                wait_for_notification(SAFETY_CHECK_SECONDS, lambda: stopping)
            except (OperationalError, InterfaceError) as exc:
                # The database went away (restart, network): reconnect and listen again.
                log.warning("menu worker: database connection lost (%s)", exc)
                connection.close()
                time.sleep(RECONNECT_SECONDS)

    def _run_next(self, stopping) -> bool:
        """Run one task, a menu generation first if there is one. False when both queues
        are empty."""
        started = time.monotonic()
        if (generation := menus.claim_next()) is not None:
            self.stdout.write(f"Generating {generation.menu} ({generation.pk})...")
            with attribute(team=generation.menu.team_id, feature=Feature.MENU):
                menus.run_generation(generation, should_stop=stopping)
            done = f"Generation {generation.pk}: {generation.status}"
        elif (job := imports.claim_next()) is not None:
            # An administrator waits for it, as for a menu.
            self.stdout.write(f"Importing {job.file_name!r} ({job.pk})...")
            imports.run_job(job)
            done = f"Import {job.pk}: {job.status}"
        elif (draft := drafts.claim_next()) is not None:
            self.stdout.write(f"Drafting system recipe {draft.dish!r} ({draft.pk})...")
            with attribute(team=Team.system(), feature=Feature.SYSTEM_DRAFTS):
                drafts.run_draft(draft, should_stop=stopping)
            done = f"Draft {draft.pk}: {draft.status}"
        elif (campaign := campaigns.next_to_plan()) is not None:
            # Only with no draft waiting: each round knows every dish drafted so far.
            self.stdout.write(f"Planning campaign {campaign.name!r}...")
            with attribute(team=Team.system(), feature=Feature.SYSTEM_DRAFTS):
                planned = campaigns.plan(campaign, get_chat_provider())
            if not planned:
                return False
            done = f"Campaign {campaign.pk}: {planned} dish(es) queued"
        else:
            return False
        self.stdout.write(f"{done} in {time.monotonic() - started:.0f} s.")
        return True
