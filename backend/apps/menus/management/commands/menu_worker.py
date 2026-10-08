"""Run queued menu generations, one at a time, until stopped.

`docker compose` runs it as the `worker` service; in native development run it beside
`runserver`. One worker is enough: generations wait for the LLM, which serves one request at a
time anyway. On start, generations a previous worker left running are marked failed.

The queue is the `MenuGeneration` table. The worker sleeps in PostgreSQL's `LISTEN` and is woken
by the `NOTIFY` the API sends when it queues a generation (`generation.notify_worker`), so it
starts at once and asks the database nothing while idle. A notification is not stored: one
sent while the worker was down or reconnecting is lost, so the worker also looks at the queue
every SAFETY_CHECK_SECONDS, and always when it starts.
"""

import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError, connection

from apps.menus.generation import CHANNEL, claim_next, fail_interrupted, run_generation

log = logging.getLogger(__name__)

# The safety net for lost notifications: one query a minute while idle.
SAFETY_CHECK_SECONDS = 60
# How often a wait looks at the stop flag. Local: no query is sent.
STOP_CHECK_SECONDS = 1
RECONNECT_SECONDS = 5


def listen() -> None:
    """Subscribe this process's database connection to the channel. Harmless if already
    subscribed; needed again after a reconnection."""
    with connection.cursor() as cursor:
        cursor.execute(f"LISTEN {CHANNEL}")


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
    help = "Run queued menu generations in the background."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run what is queued, then exit.")

    def handle(self, *args, once=False, **options):
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        if interrupted := fail_interrupted():
            self.stdout.write(f"Marked {interrupted} interrupted generation(s) as failed.")
        self.stdout.write("Menu worker started.")
        while not stopping:
            try:
                # Listen before looking at the queue: a generation queued in between is then
                # both in the queue and announced, never missed.
                listen()
                while not stopping and (generation := claim_next()) is not None:
                    self._run(generation, lambda: stopping)
                if once:
                    break
                wait_for_notification(SAFETY_CHECK_SECONDS, lambda: stopping)
            except (OperationalError, InterfaceError) as exc:
                # The database went away (restart, network): reconnect and listen again.
                log.warning("menu worker: database connection lost (%s)", exc)
                connection.close()
                time.sleep(RECONNECT_SECONDS)

    def _run(self, generation, stopping) -> None:
        self.stdout.write(f"Generating {generation.menu} ({generation.pk})...")
        started = time.monotonic()
        run_generation(generation, should_stop=stopping)
        self.stdout.write(
            f"Generation {generation.pk}: {generation.status} in "
            f"{time.monotonic() - started:.0f} s."
        )
