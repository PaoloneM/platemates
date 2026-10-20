"""The Socket.IO server of the `realtime` service, served at `/websocket/`.

A browser connects with the session cookie it already has (no token is ever sent to it): the
server loads the Django session, refuses anyone not signed in, and puts the connection in the
rooms of the user's teams. Origins are those the app is served from, as for CSRF. Browsers only
listen; events come from the backend and the worker through Redis (`events.publish`).
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from importlib import import_module
from types import SimpleNamespace

import socketio
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user
from django.db import close_old_connections

from apps.core.planes import ADMIN, plane_of
from apps.teams.models import Membership

from .events import ADMIN_ROOM, STAFF_ROOM, team_room


def user_from_cookies(cookie_header: str):
    """The signed-in user of a request's cookies, as Django's own session middleware would see
    it (including the session hash check), or None."""
    cookies = SimpleCookie()
    cookies.load(cookie_header or "")
    morsel = cookies.get(settings.SESSION_COOKIE_NAME)
    if morsel is None:
        return None
    session = import_module(settings.SESSION_ENGINE).SessionStore(morsel.value)
    user = get_user(SimpleNamespace(session=session))
    return user if user.is_authenticated else None


def rooms_of(cookie_header: str, plane: str | None = None) -> tuple[int, list[str]] | None:
    """The user's id and the rooms they may join, or None if not signed in. The staff and
    administrators' rooms only on the admin plane (apps/core/planes.py)."""
    close_old_connections()
    try:
        user = user_from_cookies(cookie_header)
        if user is None:
            return None
        teams = Membership.objects.filter(user=user).values_list("team_id", flat=True)
        rooms = [team_room(team) for team in teams]
        admin_plane = (plane or settings.DEFAULT_PLANE) == ADMIN
        if admin_plane and user.is_staff:
            rooms.append(STAFF_ROOM)
        if admin_plane and getattr(getattr(user, "profile", None), "is_admin", False):
            rooms.append(ADMIN_ROOM)
        return user.pk, rooms
    finally:
        close_old_connections()


sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(settings.REALTIME_REDIS_URL),
    cors_allowed_origins=settings.REALTIME_ALLOWED_ORIGINS,
)


@sio.event
async def connect(sid, environ, auth=None):
    found = await sync_to_async(rooms_of)(environ.get("HTTP_COOKIE", ""), plane_of(environ))
    if found is None:
        raise socketio.exceptions.ConnectionRefusedError("not signed in")
    user_id, rooms = found
    for room in rooms:
        await sio.enter_room(sid, room)
    await sio.save_session(sid, {"user": user_id})
