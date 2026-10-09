"""Sending real-time events to the browsers of a team, from any process (backend, worker).

Events go through Redis to the `realtime` service, which delivers them to the team's room. They
are notices, not data to rely on: a browser that was disconnected misses them, so it reloads the
state from the API when it reconnects. Sending never fails the caller: without Redis or the
realtime service, events are simply lost.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import socketio
from django.conf import settings

log = logging.getLogger(__name__)


def team_room(team_id: int) -> str:
    return f"team-{team_id}"


@lru_cache(maxsize=1)
def _manager() -> socketio.RedisManager:
    return socketio.RedisManager(settings.REALTIME_REDIS_URL, write_only=True)


def _emit(event: str, data: dict[str, Any], room: str) -> None:
    _manager().emit(event, data, room=room)


# Staff's own room: the progress of system recipe drafts.
STAFF_ROOM = "staff"


def publish(team_id: int, event: str, data: dict[str, Any]) -> None:
    publish_to(team_room(team_id), event, data)


def publish_to(room: str, event: str, data: dict[str, Any]) -> None:
    try:
        _emit(event, data, room)
    except Exception as exc:
        log.warning("realtime: could not send %s to %s (%s)", event, room, exc)
