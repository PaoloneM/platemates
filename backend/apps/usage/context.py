"""On whose behalf AI calls are made: set where the work starts, read where usage is recorded.

    with attribute(team=session.team, feature=Feature.ASSISTANT):
        run_turn(...)

A context variable, so it follows the call through the code without being passed around. Threads
started inside do not inherit it: run their work through `carry()`.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .models import Feature


@dataclass(frozen=True)
class Attribution:
    team_id: int | None
    feature: str


_current: contextvars.ContextVar[Attribution | None] = contextvars.ContextVar(
    "ai_usage_attribution", default=None
)


def current() -> Attribution:
    return _current.get() or Attribution(team_id=None, feature=Feature.OTHER)


@contextmanager
def attribute(*, team=None, feature: str) -> Iterator[None]:
    token = _current.set(Attribution(team_id=getattr(team, "pk", team), feature=feature))
    try:
        yield
    finally:
        _current.reset(token)


def carry(function: Callable[..., Any]) -> Callable[..., Any]:
    """`function`, run with the caller's attribution when a thread pool calls it."""
    context = contextvars.copy_context()

    def run(*args, **kwargs):
        # A copy per call: one context cannot be entered by two threads at once.
        return context.copy().run(function, *args, **kwargs)

    return run
