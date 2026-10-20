"""Sending real-time events to the browsers of a team, from any process (backend, worker).

Events go through Redis to the `realtime` service, which delivers them to the team's room. They
are notices, not data to rely on: a browser that was disconnected misses them, so it reloads the
state from the API when it reconnects. Sending never fails the caller: without Redis or the
realtime service, events are simply lost.
"""

from __future__ import annotations

import contextvars
import logging
from functools import lru_cache
from typing import Any

import socketio
from django.conf import settings

log = logging.getLogger(__name__)


# The browser tab whose request is being served (header X-PlateMates-Client, set by the SPA on
# every API call). Events carry it as `origin`, so that tab knows the change is its own: it
# updates without the highlight other tabs show.
_origin: contextvars.ContextVar[str] = contextvars.ContextVar("realtime_origin", default="")
ORIGIN_HEADER = "HTTP_X_PLATEMATES_CLIENT"


class OriginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _origin.set(request.META.get(ORIGIN_HEADER, "")[:64])
        try:
            return self.get_response(request)
        finally:
            _origin.reset(token)


def team_room(team_id: int) -> str:
    return f"team-{team_id}"


@lru_cache(maxsize=1)
def _manager() -> socketio.RedisManager:
    return socketio.RedisManager(settings.REALTIME_REDIS_URL, write_only=True)


def _emit(event: str, data: dict[str, Any], room: str) -> None:
    _manager().emit(event, data, room=room)


# Staff's own room: the progress of system recipe drafts.
STAFF_ROOM = "staff"
# The administrators' room: the progress of imports.
ADMIN_ROOM = "admin"


def publish(team_id: int, event: str, data: dict[str, Any]) -> None:
    publish_to(team_room(team_id), event, data)


def publish_teams(team_ids, event: str, data: dict[str, Any]) -> None:
    for team_id in sorted(set(team_ids)):
        publish(team_id, event, data)


def publish_on_commit(team_ids, event: str, data: dict[str, Any]) -> None:
    """Send once the change is saved, saying which tab made it (read now: the commit may come
    after the request)."""
    from django.db import transaction

    if origin := _origin.get():
        data = {**data, "origin": origin}
    teams = sorted(set(team_ids))
    transaction.on_commit(lambda: publish_teams(teams, event, data))


def publish_to(room: str, event: str, data: dict[str, Any]) -> None:
    if "origin" not in data and (origin := _origin.get()):
        data = {**data, "origin": origin}
    try:
        _emit(event, data, room)
    except Exception as exc:
        log.warning("realtime: could not send %s to %s (%s)", event, room, exc)
