"""The public plane and the admin plane: where a request comes from decides what it may do.

On the public server two Traefik instances reach the same backend:
- the **public** one, on ports 80/443, serves the app;
- the **admin** one listens only on the VM's 127.0.0.1 (reached through an SSH tunnel) and
  serves Gestione, Django admin, Keycloak's console and Grafana.

Each sets the `X-PlateMates-Plane` header on every request, overwriting whatever the client
sent, and the backend's own port is never published: the header can be trusted. Without it
(a request outside Traefik, the worker, a command) the plane is `settings.DEFAULT_PLANE`:
`admin` on a developer's machine, `public` on the server, so a missing header grants nothing.

Staff and administrator powers exist **only on the admin plane**: every check of `is_staff` or
of the `admin` role goes through `staff_powers` / `admin_powers`, so a staff account signed in
on the public plane is an ordinary user there.
"""

from __future__ import annotations

import contextvars

from django.conf import settings
from django.http import HttpResponseNotFound

ADMIN = "admin"
PUBLIC = "public"
HEADER = "HTTP_X_PLATEMATES_PLANE"

# Served on the admin plane only: answered 404 on the public one (the public Traefik does not
# route them either).
ADMIN_ONLY_PATHS = (
    "/admin/",
    "/api/config/",
    "/api/cache/",
    "/api/usage/",
    "/api/search-probe/",
    "/api/audit-stats/",
    "/api/invite-requests/",
    "/api/transfer/",
    "/api/system-drafts/",
)

_plane: contextvars.ContextVar[str | None] = contextvars.ContextVar("plane", default=None)


def plane_of(meta) -> str:
    value = (meta.get(HEADER) or "").strip().lower()
    return value if value in (ADMIN, PUBLIC) else settings.DEFAULT_PLANE


def current() -> str:
    return _plane.get() or settings.DEFAULT_PLANE


def on_admin_plane() -> bool:
    return current() == ADMIN


def staff_powers(user) -> bool:
    """Staff, and on the admin plane."""
    return bool(user is not None and user.is_authenticated and user.is_staff and on_admin_plane())


def admin_powers(user) -> bool:
    """Holder of Keycloak's `admin` role, and on the admin plane."""
    profile = getattr(user, "profile", None) if user is not None else None
    return bool(
        user is not None
        and user.is_authenticated
        and getattr(profile, "is_admin", False)
        and on_admin_plane()
    )


class PlaneMiddleware:
    """Sets the request's plane for everything below it, and hides admin-only paths from the
    public plane."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        plane = plane_of(request.META)
        request.plane = plane
        if plane == PUBLIC and request.path.startswith(ADMIN_ONLY_PATHS):
            return HttpResponseNotFound()
        token = _plane.set(plane)
        try:
            return self.get_response(request)
        finally:
            _plane.reset(token)
