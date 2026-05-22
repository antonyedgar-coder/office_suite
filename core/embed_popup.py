"""Embed popup helpers — open full Settings create forms in an iframe from master pickers."""

from __future__ import annotations

import json
from typing import Any

from functools import wraps

from django.http import HttpRequest
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin

PICKER_CLIENT_TYPE = "clientType"
PICKER_CLIENT_GROUP = "clientGroup"
PICKER_TASK_MASTER = "taskMaster"
PICKER_PORTAL_NAME = "portalName"

EMBED_QUERY = "embed"
EMBED_VALUE = "popup"


def embed_popup_request(request: HttpRequest) -> bool:
    return (request.GET.get(EMBED_QUERY) or request.POST.get(EMBED_QUERY) or "").strip() == EMBED_VALUE


def embed_popup_context(request: HttpRequest, **extra: Any) -> dict[str, Any]:
    embed = embed_popup_request(request)
    return {
        "embed_popup": embed,
        **extra,
    }


def embed_form_template(request: HttpRequest, *, normal: str, popup: str) -> str:
    """Pick the full-page or iframe popup template for a master create/edit form."""
    return popup if embed_popup_request(request) else normal


def allow_embed_popup_frame(view_func):
    """Ensure master create forms can render inside same-origin iframe pickers."""

    @xframe_options_sameorigin
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)

    return _wrapped


def render_popup_created(
    request: HttpRequest,
    *,
    picker_kind: str,
    item_id: str | int,
    item_label: str,
    extra: dict[str, Any] | None = None,
):
    return render(
        request,
        "embed/popup_created.html",
        {
            "picker_kind": picker_kind,
            "item_id": item_id,
            "item_label": item_label,
            "extra_json": json.dumps(extra or {}),
        },
    )
