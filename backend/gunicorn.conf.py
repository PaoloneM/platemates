"""Gunicorn's own hooks (the rest of its settings are on its command line, in the Dockerfile)."""

from prometheus_client import multiprocess


def child_exit(server, worker):
    # A worker that stops leaves its metric files: mark them, so gauges do not count it.
    multiprocess.mark_process_dead(worker.pid)
