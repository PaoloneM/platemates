"""ASGI entry point of the `realtime` service: `uvicorn apps.realtime.asgi:app`."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import socketio  # noqa: E402

from .server import sio  # noqa: E402

app = socketio.ASGIApp(sio, socketio_path="websocket")
