"""Stores what `ai/` reports (ai/usage.py), with the current attribution."""

from __future__ import annotations

from ai.usage import Usage

from .context import current
from .models import AIUsage


def record(usage: Usage) -> None:
    attribution = current()
    AIUsage.objects.create(
        team_id=attribution.team_id,
        feature=attribution.feature,
        provider=usage.provider,
        model=usage.model,
        operation=usage.operation,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        web_searches=usage.web_searches,
    )
