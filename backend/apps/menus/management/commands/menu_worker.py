"""Run queued menu generations, one at a time, until stopped.

`docker compose` runs it as the `worker` service; in native development run it beside
`runserver`. One worker is enough: generations wait for the LLM, which serves one request at a
time anyway. On start, generations a previous worker left running are marked failed.
"""

import signal
import time

from django.core.management.base import BaseCommand

from apps.menus.generation import claim_next, fail_interrupted, run_generation

POLL_SECONDS = 2


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
            generation = claim_next()
            if generation is None:
                if once:
                    break
                time.sleep(POLL_SECONDS)
                continue
            self.stdout.write(f"Generating {generation.menu} ({generation.pk})...")
            started = time.monotonic()
            run_generation(generation)
            self.stdout.write(
                f"Generation {generation.pk}: {generation.status} in "
                f"{time.monotonic() - started:.0f} s."
            )
