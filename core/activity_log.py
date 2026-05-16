"""Helpers for persisting audit-style activity entries."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl

if TYPE_CHECKING:
    from django.http import HttpRequest

    from .models import User

# Client Master IDs: two letters + four digits (AN0001) or legacy one letter + five (A00001).
_CLIENT_ID_FULL_RE = re.compile(r"^(?:[A-Za-z]{2}\d{4}|[A-Za-z]\d{5})$")


def client_ip(request: HttpRequest) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip() or None
    addr = request.META.get("REMOTE_ADDR")
    return addr or None


def enrich_activity_log_description(request: HttpRequest, base_description: str) -> str:
    """
    Replace bare client IDs in the logged path/detail string with "ID (Client name)"
    when the ID matches a Client Master record (full six-character IDs only).
    """
    from masters.models import Client

    match = getattr(request, "resolver_match", None)
    kwargs = getattr(match, "kwargs", None) or {}

    id_candidates: list[str] = []
    kw_cid = kwargs.get("client_id")
    if kw_cid:
        s = str(kw_cid).strip()
        if len(s) <= 6 and _CLIENT_ID_FULL_RE.match(s):
            id_candidates.append(s.upper())

    q = request.META.get("QUERY_STRING", "")
    if q:
        for key, raw_val in parse_qsl(q, keep_blank_values=False):
            if key.lower() not in ("client_id", "clients"):
                continue
            s = (raw_val or "").strip()
            if len(s) <= 6 and _CLIENT_ID_FULL_RE.match(s):
                id_candidates.append(s.upper())

    unique: list[str] = []
    seen: set[str] = set()
    for u in id_candidates:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    if not unique:
        return base_description[:2000]

    rows = list(Client.objects.filter(client_id__in=unique).values_list("client_id", "client_name"))
    by_upper = {r[0].upper(): (r[0], r[1]) for r in rows}

    out = base_description
    for u in unique:
        got = by_upper.get(u)
        if not got:
            continue
        cid, cname = got
        esc = re.escape(cid)

        def _path_masters(m: re.Match, cid: str = cid, cname: str = cname) -> str:
            return f"{m.group(1)}{cid} ({cname})"

        def _path_clients(m: re.Match, cid: str = cid, cname: str = cname) -> str:
            return f"{m.group(1)}{cid} ({cname})"

        def _q_client_id(m: re.Match, cid: str = cid, cname: str = cname) -> str:
            return f"{m.group(1)}client_id={cid} ({cname})"

        def _q_clients(m: re.Match, cid: str = cid, cname: str = cname) -> str:
            return f"{m.group(1)}clients={cid} ({cname})"

        out = re.sub(
            rf"(?i)(/masters/clients/)({esc})(?=[/?]|$)",
            _path_masters,
            out,
        )
        out = re.sub(
            rf"(?i)(/clients/)({esc})(?=[/?]|$)",
            _path_clients,
            out,
        )
        out = re.sub(
            rf"(?i)([?&])client_id={esc}(?=&|$)",
            _q_client_id,
            out,
        )
        out = re.sub(
            rf"(?i)([?&])clients={esc}(?=&|$)",
            _q_clients,
            out,
        )

    return out[:2000]


def log_activity_from_request(
    *,
    user: User,
    request: HttpRequest,
    method: str,
    path: str,
    status_code: int | None = None,
    description: str = "",
) -> None:
    from .models import ActivityLog

    ActivityLog.objects.create(
        user=user,
        user_email=(user.email[:254] if getattr(user, "email", None) else ""),
        method=method[:16],
        path=path[:512],
        status_code=status_code,
        description=(description[:2000] if description else ""),
        ip_address=client_ip(request),
    )
