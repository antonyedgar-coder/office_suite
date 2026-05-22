from __future__ import annotations

import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from masters.client_activity import log_client_activity
from masters.models import Client, ClientActivityLog

from .models import (
    ClientDocument,
    ClientDocumentFolder,
    DocumentFolderTemplate,
    DocumentTypeTemplate,
)
from .periods import build_standard_filename, extract_fy_from_period_key, resolve_period
from .task_bridge import user_can_change_task_linked_document


def folder_templates_for_client(client: Client):
    """Master folders applicable to this client's type (active only)."""
    from django.db.models import Count, Q

    ct = (client.client_type or "").strip()
    qs = DocumentFolderTemplate.objects.filter(is_active=True).annotate(
        type_count=Count("client_types")
    )
    if not ct:
        return qs.filter(type_count=0).order_by("sort_order", "name")
    return (
        qs.filter(Q(type_count=0) | Q(client_types__name=ct))
        .distinct()
        .order_by("sort_order", "name")
    )


def existing_folder_template_ids(client: Client) -> set[int]:
    return set(
        ClientDocumentFolder.objects.filter(client=client).values_list("template_id", flat=True)
    )


def create_client_document_folders(
    client: Client,
    template_ids: list[int],
    *,
    user,
) -> int:
    """Create only selected master folders for an approved client."""
    if client.approval_status != Client.APPROVED:
        raise ValidationError("Document folders can only be created for approved clients.")
    allowed = {t.pk for t in folder_templates_for_client(client)}
    created = 0
    for tid in template_ids:
        if tid not in allowed:
            raise ValidationError("One or more folders are not valid for this client type.")
        tmpl = DocumentFolderTemplate.objects.filter(pk=tid, is_active=True).first()
        if not tmpl:
            continue
        _, was_created = ClientDocumentFolder.objects.get_or_create(
            client=client,
            template=tmpl,
        )
        if was_created:
            created += 1
    if created:
        log_client_activity(
            client=client,
            user=user,
            category=ClientActivityLog.CATEGORY_CLIENT,
            activity=f"Document folders created ({created} new).",
            metadata={"document_folders_created": created, "template_ids": template_ids},
        )
    return created


def provision_client_document_folders(client: Client) -> int:
    """Management command helper: create all applicable templates for a client."""
    if client.approval_status != Client.APPROVED:
        return 0
    ids = list(folder_templates_for_client(client).values_list("pk", flat=True))
    return create_client_document_folders(client, ids, user=None)


def _sanitize_filename_part(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120] or "Document"


def render_generated_filename(
    template: DocumentTypeTemplate,
    *,
    client: Client,
    period_key: str,
    period_label: str,
    extension: str,
) -> str:
    return build_standard_filename(
        document_type_name=template.name,
        client_name=client.client_name,
        period_kind=template.period_kind,
        period_key=period_key,
        extension=extension,
        sanitize=_sanitize_filename_part,
    )


def _file_extension(filename: str, content_type: str = "") -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext:
        return ext
    mime_map = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.ms-excel": "xls",
        "image/jpeg": "jpg",
        "image/png": "png",
    }
    return mime_map.get((content_type or "").split(";")[0].strip(), "")


def validate_upload_file(uploaded_file, document_type: DocumentTypeTemplate) -> str:
    if not uploaded_file:
        raise ValidationError("Choose a file to upload.")
    size = getattr(uploaded_file, "size", 0) or 0
    max_bytes = getattr(settings, "DOCUMENT_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
    if size > max_bytes:
        raise ValidationError(
            f"File is too large (max {max_bytes // (1024 * 1024)} MB)."
        )
    ext = _file_extension(uploaded_file.name, getattr(uploaded_file, "content_type", ""))
    allowed = document_type.allowed_extension_set()
    if not ext or ext not in allowed:
        allowed_txt = ", ".join(sorted(allowed))
        raise ValidationError(
            f"This document type only allows: {allowed_txt}."
        )
    return ext


def compute_content_hash(uploaded_file) -> str:
    h = hashlib.sha256()
    if hasattr(uploaded_file, "chunks"):
        for chunk in uploaded_file.chunks():
            h.update(chunk)
    else:
        h.update(uploaded_file.read())
    uploaded_file.seek(0)
    return h.hexdigest()


def _active_document_queryset(
    *,
    client: Client,
    folder: ClientDocumentFolder,
    document_type: DocumentTypeTemplate,
    period_key: str,
):
    return ClientDocument.objects.filter(
        client=client,
        folder=folder,
        document_type=document_type,
        period_key=period_key,
        status=ClientDocument.STATUS_ACTIVE,
    )


@transaction.atomic
def _require_document_editable(user, doc: ClientDocument | None = None, *, task=None) -> None:
    if doc and not user_can_change_task_linked_document(user, doc, task=task):
        raise ValidationError(
            "This document is locked because the linked task is complete. "
            "Use document rework on the task, or ask an administrator with override permission."
        )


def save_client_document(
    *,
    client: Client,
    folder: ClientDocumentFolder,
    document_type: DocumentTypeTemplate,
    period_key: str,
    period_label: str,
    uploaded_file,
    user,
    task=None,
) -> ClientDocument:
    if folder.client_id != client.pk:
        raise ValidationError("Folder does not belong to this client.")
    if document_type.folder_id != folder.template_id:
        raise ValidationError("Document type does not belong to this folder.")

    period_key = (period_key or "once").strip()
    period_label = (period_label or "").strip()

    ext = validate_upload_file(uploaded_file, document_type)
    content_hash = compute_content_hash(uploaded_file)
    generated = render_generated_filename(
        document_type,
        client=client,
        period_key=period_key,
        period_label=period_label,
        extension=ext,
    )

    active_qs = _active_document_queryset(
        client=client,
        folder=folder,
        document_type=document_type,
        period_key=period_key,
    )
    active = active_qs.select_for_update().first()
    if active:
        _require_document_editable(user, active, task=task)
    if active and active.content_hash == content_hash:
        raise ValidationError(
            "This file is identical to the current version already on file."
        )

    next_version = 1
    if active:
        next_version = active.version + 1
        active.status = ClientDocument.STATUS_SUPERSEDED
        active.save(update_fields=["status"])

    fy_legacy = extract_fy_from_period_key(period_key)
    link_task = task
    if link_task is None and active and active.task_id:
        link_task = active.task

    doc = ClientDocument(
        client=client,
        folder=folder,
        document_type=document_type,
        period_key=period_key,
        period_label=period_label,
        financial_year=fy_legacy,
        generated_filename=generated,
        content_hash=content_hash,
        version=next_version,
        status=ClientDocument.STATUS_ACTIVE,
        original_filename=(uploaded_file.name or "")[:255],
        uploaded_by=user,
        task=link_task,
    )
    doc.file.save(generated, uploaded_file, save=False)
    doc.save()

    log_client_activity(
        client=client,
        user=user,
        category=ClientActivityLog.CATEGORY_CLIENT,
        activity=f"Document uploaded: {generated} (v{next_version}).",
        metadata={
            "document_id": doc.pk,
            "folder": folder.template.name,
            "document_type": document_type.name,
            "period_key": period_key,
            "period_label": period_label,
            "version": next_version,
            "task_id": link_task.pk if link_task else None,
        },
    )
    return doc


@transaction.atomic
def replace_client_document(
    doc: ClientDocument,
    *,
    uploaded_file,
    user,
) -> ClientDocument:
    """Replace file only; folder, type, and period stay the same (new version)."""
    if doc.status != ClientDocument.STATUS_ACTIVE:
        raise ValidationError("Only active files can be replaced.")
    _require_document_editable(user, doc)
    new_doc = save_client_document(
        client=doc.client,
        folder=doc.folder,
        document_type=doc.document_type,
        period_key=doc.period_key,
        period_label=doc.period_label,
        uploaded_file=uploaded_file,
        user=user,
        task=doc.task,
    )
    if doc.task_id and not new_doc.task_id:
        new_doc.task_id = doc.task_id
        new_doc.save(update_fields=["task"])
    log_client_activity(
        client=doc.client,
        user=user,
        category=ClientActivityLog.CATEGORY_CLIENT,
        activity=f"Document replaced: {new_doc.generated_filename} (v{new_doc.version}).",
        metadata={
            "document_id": new_doc.pk,
            "replaced_document_id": doc.pk,
            "version": new_doc.version,
        },
    )
    return new_doc


@transaction.atomic
def delete_client_document(doc: ClientDocument, *, user) -> None:
    """Remove an active client document and its stored file."""
    if doc.status != ClientDocument.STATUS_ACTIVE:
        raise ValidationError("Only active files can be deleted.")
    _require_document_editable(user, doc)

    client = doc.client
    label = doc.generated_filename
    meta = {
        "document_id": doc.pk,
        "folder": doc.folder.template.name if doc.folder_id else "",
        "document_type": doc.document_type.name if doc.document_type_id else "",
        "period_key": doc.period_key,
        "period_label": doc.period_label,
        "version": doc.version,
    }
    if doc.file:
        doc.file.delete(save=False)
    doc.delete()
    log_client_activity(
        client=client,
        user=user,
        category=ClientActivityLog.CATEGORY_CLIENT,
        activity=f"Document deleted: {label}.",
        metadata=meta,
    )


def parse_upload_period(document_type: DocumentTypeTemplate, data: dict) -> tuple[str, str]:
    return resolve_period(
        document_type.period_kind,
        period_month=data.get("period_month") or "",
        period_fy=data.get("period_fy") or "",
        period_quarter=data.get("period_quarter") or "",
        period_half=data.get("period_half") or "",
    )


def document_types_for_folder_json() -> dict[str, list[dict]]:
    """Map folder template pk -> document type options for upload form JS."""
    out: dict[str, list[dict]] = {}
    types = (
        DocumentTypeTemplate.objects.filter(is_active=True, folder__is_active=True)
        .select_related("folder")
        .order_by("sort_order", "name")
    )
    for dt in types:
        key = str(dt.folder_id)
        out.setdefault(key, []).append(
            {
                "id": dt.pk,
                "label": dt.name,
                "period_kind": dt.period_kind,
                "extensions": sorted(dt.allowed_extension_set()),
            }
        )
    return out
