"""Export and import, for application administrators (Management > Export / import)."""

from __future__ import annotations

import json

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
    renderer_classes,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from apps.catalog.models import Ingredient
from apps.core.permissions import IsAppAdmin
from apps.recipes.models import Recipe
from apps.teams.models import Team

from .exporting import export_ingredients, export_recipes, export_system, export_team
from .importing import MODES, Importer, TransferError
from .jobs import notify_worker
from .models import ImportJob


def _ids(value: str) -> list[int]:
    return [int(v) for v in value.split(",") if v.strip().isdigit()]


@api_view(["GET"])
@permission_classes([IsAppAdmin])
# Always the JSON file, also when a browser opens the link (it asks for HTML, which would get
# the browsable API page instead of the document).
@renderer_classes([JSONRenderer])
def export_view(request):
    """`?scope=team&team=<id>`, `?scope=recipes&ids=1,2`, `?scope=ingredients&ids=...` or
    `&owner=system`, `?scope=system`: the document, as a file to save."""
    params = request.query_params
    scope = params.get("scope")
    if scope == "team":
        team = Team.objects.filter(pk=params.get("team"), is_system=False).first()
        if team is None:
            return Response({"team": "Choose a team."}, status=status.HTTP_400_BAD_REQUEST)
        document, label = export_team(team), team.name
    elif scope == "recipes":
        ids = _ids(params.get("ids", ""))
        if not ids:
            return Response({"ids": "Choose recipes."}, status=status.HTTP_400_BAD_REQUEST)
        document, label = export_recipes(ids), f"{len(ids)}"
    elif scope == "ingredients":
        if params.get("owner") == "system":
            ids = list(Ingredient.objects.system().values_list("pk", flat=True))
        else:
            ids = _ids(params.get("ids", ""))
        document, label = export_ingredients(ids), params.get("owner", f"{len(ids)}")
    elif scope == "system":
        document, label = export_system(), ""
    else:
        return Response({"scope": "Unknown scope."}, status=status.HTTP_400_BAD_REQUEST)
    name = "-".join(
        filter(None, ["platemates", scope, slugify(label), timezone.localdate().isoformat()])
    )
    response = Response(document)
    response["Content-Disposition"] = f'attachment; filename="{name}.json"'
    return response


def _job_data(job: ImportJob) -> dict:
    return {
        "id": job.pk,
        "file_name": job.file_name,
        "dry_run": job.dry_run,
        "status": job.status,
        "phase": job.phase,
        "done": job.done,
        "total": job.total,
        "report": job.report,
        "error": job.error,
        "created_at": job.created_at,
    }


def _queue(**fields) -> ImportJob:
    with transaction.atomic():
        job = ImportJob.objects.create(**fields)
        notify_worker()
    return job


@api_view(["POST"])
@permission_classes([IsAppAdmin])
@parser_classes([MultiPartParser])
def import_view(request):
    """Multipart: `file` (an export), `mode` (skip | update), `target_team` (id, or empty for
    the team with the file's identity, else a new one), `dry_run` (true: preview only). The
    import runs in the worker: 202 with the job, followed at `jobs/<id>/` and live (`transfer`
    events in the administrators' room)."""
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"file": "Choose a file."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        document = json.loads(upload.read())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response({"file": "Not a JSON file."}, status=status.HTTP_400_BAD_REQUEST)
    mode = request.data.get("mode", "skip")
    target = None
    if target_id := request.data.get("target_team"):
        target = Team.objects.filter(pk=target_id, is_system=False).first()
        if target is None:
            return Response({"target_team": "No such team."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        # The file's format, version and the mode are checked now, not in the worker.
        Importer(document, user=request.user, mode=mode if mode in MODES else "")
    except TransferError as exc:
        return Response({"file": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    job = _queue(
        created_by=request.user,
        file_name=upload.name[:255],
        document=document,
        mode=mode,
        target_team=target,
        dry_run=str(request.data.get("dry_run", "true")).lower() != "false",
    )
    return Response(_job_data(job), status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@permission_classes([IsAppAdmin])
def job_view(request, pk: int):
    job = ImportJob.objects.filter(pk=pk).first()
    if job is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(_job_data(job))


@api_view(["POST"])
@permission_classes([IsAppAdmin])
def confirm_view(request, pk: int):
    """Import for real the file a finished preview read, with the same options."""
    preview = ImportJob.objects.filter(pk=pk, dry_run=True, status=ImportJob.Status.DONE).first()
    if preview is None or not preview.document:
        return Response({"detail": "Preview the file first."}, status=status.HTTP_400_BAD_REQUEST)
    job = _queue(
        created_by=request.user,
        file_name=preview.file_name,
        document=preview.document,
        mode=preview.mode,
        target_team=preview.target_team,
        dry_run=False,
    )
    return Response(_job_data(job), status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@permission_classes([IsAppAdmin])
def choices_view(request):
    """What can be exported: the teams, and recipes matching `?search=`."""
    teams = (
        Team.objects.filter(is_system=False)
        .annotate(
            recipes=Count("owned_recipes", distinct=True), people=Count("users", distinct=True)
        )
        .order_by("name")
    )
    recipes = []
    if search := request.query_params.get("search", "").strip():
        recipes = [
            {"id": r.pk, "title": r.title, "team": r.owner_team.name if r.owner_team else None}
            for r in Recipe.objects.filter(title__icontains=search)
            .select_related("owner_team")
            .order_by("title")[:20]
        ]
    return Response(
        {
            "teams": [
                {"id": t.pk, "name": t.name, "recipes": t.recipes, "users": t.people} for t in teams
            ],
            "recipes": recipes,
            "system_ingredients": Ingredient.objects.system().count(),
        }
    )
