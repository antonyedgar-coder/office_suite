from __future__ import annotations

import hashlib
import logging
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
from .folder_constants import (
    KYC_DOCUMENTS_SLUG,
    LEGACY_KYC_SLUG,
    SUPPORTING_DOCUMENTS_SLUG,
)
from .periods import (
    build_custom_user_filename,
    build_plain_display_filename,
    build_one_time_task_filename,
    build_standard_filename,
    extract_fy_from_period_key,
    resolve_period,
)
from .task_bridge import user_can_change_task_linked_document

logger = logging.getLogger(__name__)


def _save_uploaded_file(doc: ClientDocument, generated: str, uploaded_file) -> None:
    """Persist file to local disk or Spaces; surface a clear error instead of HTTP 500."""
    try:
        doc.file.save(generated, uploaded_file, save=False)
    except Exception as exc:
        logger.exception(
            "Document file save failed (client=%s folder=%s name=%s)",
            doc.client_id,
            doc.folder_id,
            generated,
        )
        storage = getattr(settings, "DOCUMENT_STORAGE", "local")
        if storage == "spaces":
            raise ValidationError(
                "Could not save the file to cloud storage. "
                "Check that Spaces credentials, bucket name, and endpoint are correct "
                "(Settings → App → Environment variables), and that the access key has "
                "Read/Write/Delete on the bucket."
            ) from exc
        raise ValidationError(
            "Could not save the uploaded file. Please try again or contact support."
        ) from exc


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


def ensure_standard_folder_templates() -> list[DocumentFolderTemplate]:
    """Create or update Supporting Documents and KYC Documents master folders."""
    supporting, _ = DocumentFolderTemplate.objects.update_or_create(
        slug=SUPPORTING_DOCUMENTS_SLUG,
        defaults={
            "name": "Supporting Documents",
            "sort_order": 5,
            "is_active": True,
            "allow_custom_filename": True,
        },
    )
    kyc = DocumentFolderTemplate.objects.filter(slug=KYC_DOCUMENTS_SLUG).first()
    if not kyc:
        legacy = DocumentFolderTemplate.objects.filter(slug=LEGACY_KYC_SLUG).first()
        if legacy:
            legacy.name = "KYC Documents"
            legacy.slug = KYC_DOCUMENTS_SLUG
            legacy.sort_order = 6
            legacy.is_active = True
            legacy.allow_custom_filename = False
            legacy.save(
                update_fields=["name", "slug", "sort_order", "is_active", "allow_custom_filename"]
            )
            kyc = legacy
        else:
            kyc, _ = DocumentFolderTemplate.objects.update_or_create(
                slug=KYC_DOCUMENTS_SLUG,
                defaults={
                    "name": "KYC Documents",
                    "sort_order": 6,
                    "is_active": True,
                    "allow_custom_filename": False,
                },
            )
    DocumentTypeTemplate.objects.get_or_create(
        folder=supporting,
        slug="supporting-file",
        defaults={
            "name": "Supporting file",
            "allowed_extensions": "pdf,jpg,jpeg,png,xlsx,xls,doc,docx",
            "period_kind": "none",
            "sort_order": 10,
            "is_active": True,
        },
    )
    DocumentTypeTemplate.objects.get_or_create(
        folder=kyc,
        slug="kyc-file",
        defaults={
            "name": "KYC file",
            "allowed_extensions": "pdf,jpg,jpeg,png",
            "period_kind": "none",
            "sort_order": 10,
            "is_active": True,
        },
    )
    return [supporting, kyc]


def provision_standard_client_folders(client: Client, *, user=None) -> int:
    """Create Supporting Documents and KYC Documents folders for every client."""
    templates = ensure_standard_folder_templates()
    created = 0
    for tmpl in templates:
        if not tmpl.is_active:
            continue
        _, was_created = ClientDocumentFolder.objects.get_or_create(
            client=client,
            template=tmpl,
        )
        if was_created:
            created += 1
    if created and user:
        log_client_activity(
            client=client,
            user=user,
            category=ClientActivityLog.CATEGORY_CLIENT,
            activity=f"Standard document folders created ({created}).",
            metadata={"standard_document_folders_created": created},
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
    task=None,
) -> str:
    if task is not None and (task.period_type or "").strip() == "one_time":
        master = getattr(task, "task_master", None)
        if master is None and getattr(task, "task_master_id", None):
            from tasks.models import TaskMaster

            master = TaskMaster.objects.filter(pk=task.task_master_id).first()
        if master:
            return build_one_time_task_filename(
                task_master_name=master.name,
                client_name=client.client_name,
                period_key=period_key,
                extension=extension,
                sanitize=_sanitize_filename_part,
            )
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


def _user_label_from_generated_filename(
    generated: str,
    *,
    period_key: str,
    period_label: str,
) -> str:
    """Best-effort reverse of build_custom_user_filename for replace/versioning."""
    stem = Path(generated or "").stem
    if not stem:
        return "Document"
    fy = extract_fy_from_period_key(period_key)
    pl = (period_label or "").strip()
    if fy and pl and pl not in ("Once", "—"):
        suffix = f"_FY{fy}_{_sanitize_filename_part(pl)}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)] or "Document"
    if fy:
        suffix = f"_FY{fy}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)] or "Document"
    if pl and pl not in ("Once", "—"):
        suffix = f"_{_sanitize_filename_part(pl)}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)] or "Document"
    return stem


def _ensure_unique_generated_filename(
    *,
    client: Client,
    folder: ClientDocumentFolder,
    generated: str,
    exclude_pk: int | None = None,
) -> str:
    """Avoid duplicate active filenames in multi-upload folders."""
    qs = ClientDocument.objects.filter(
        client=client,
        folder=folder,
        generated_filename=generated,
        status=ClientDocument.STATUS_ACTIVE,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if not qs.exists():
        return generated
    path = Path(generated)
    stem, ext = path.stem, path.suffix
    n = 2
    while True:
        candidate = f"{stem}_{n}{ext}" if ext else f"{stem}_{n}"
        dup = ClientDocument.objects.filter(
            client=client,
            folder=folder,
            generated_filename=candidate,
            status=ClientDocument.STATUS_ACTIVE,
        )
        if exclude_pk:
            dup = dup.exclude(pk=exclude_pk)
        if not dup.exists():
            return candidate
        n += 1


def default_document_type_for_folder(folder: ClientDocumentFolder) -> DocumentTypeTemplate | None:
    """Default file type for folders that allow free-form uploads (Supporting Documents)."""
    template = folder.template
    if not template.allow_custom_filename:
        return None
    dt = DocumentTypeTemplate.objects.filter(
        folder=template,
        slug="supporting-file",
        is_active=True,
    ).first()
    if dt:
        return dt
    return (
        DocumentTypeTemplate.objects.filter(folder=template, is_active=True)
        .order_by("sort_order", "name")
        .first()
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
    custom_display_name: str = "",
    replace_document: ClientDocument | None = None,
) -> ClientDocument:
    if folder.client_id != client.pk:
        raise ValidationError("Folder does not belong to this client.")
    if document_type.folder_id != folder.template_id:
        raise ValidationError("Document type does not belong to this folder.")

    period_key = (period_key or "once").strip()
    period_label = (period_label or "").strip()

    ext = validate_upload_file(uploaded_file, document_type)
    content_hash = compute_content_hash(uploaded_file)
    folder_template = folder.template
    custom_name = (custom_display_name or "").strip()
    if custom_name and not folder_template.allow_custom_filename:
        raise ValidationError("Custom file names are not allowed for this folder.")
    if folder_template.allow_custom_filename:
        if not custom_name:
            raise ValidationError("Enter a name for this file.")
        generated = build_plain_display_filename(
            user_label=custom_name,
            extension=ext,
            sanitize=_sanitize_filename_part,
        )
    else:
        generated = render_generated_filename(
            document_type,
            client=client,
            period_key=period_key,
            period_label=period_label,
            extension=ext,
            task=task,
        )

    multi_upload = folder_template.allow_custom_filename and replace_document is None
    if multi_upload:
        generated = _ensure_unique_generated_filename(
            client=client,
            folder=folder,
            generated=generated,
        )

    active = None
    next_version = 1
    if replace_document is not None:
        active = (
            ClientDocument.objects.select_for_update()
            .filter(
                pk=replace_document.pk,
                client=client,
                status=ClientDocument.STATUS_ACTIVE,
            )
            .first()
        )
        if not active:
            raise ValidationError("This file is no longer active and cannot be replaced.")
        _require_document_editable(user, active, task=task)
        if active.content_hash == content_hash:
            raise ValidationError(
                "This file is identical to the current version already on file."
            )
        next_version = active.version + 1
        active.status = ClientDocument.STATUS_SUPERSEDED
        active.save(update_fields=["status"])
    elif not multi_upload:
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
    _save_uploaded_file(doc, generated, uploaded_file)
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
    custom_name = ""
    if doc.folder.template.allow_custom_filename:
        custom_name = _user_label_from_generated_filename(
            doc.generated_filename,
            period_key=doc.period_key,
            period_label=doc.period_label,
        )
    new_doc = save_client_document(
        client=doc.client,
        folder=doc.folder,
        document_type=doc.document_type,
        period_key=doc.period_key,
        period_label=doc.period_label,
        uploaded_file=uploaded_file,
        user=user,
        task=doc.task,
        custom_display_name=custom_name,
        replace_document=doc,
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
def rename_client_document(
    doc: ClientDocument,
    *,
    new_display_name: str,
    user,
) -> ClientDocument:
    """Rename display filename (Supporting Documents only)."""
    if doc.status != ClientDocument.STATUS_ACTIVE:
        raise ValidationError("Only active files can be renamed.")
    _require_document_editable(user, doc)
    folder_template = doc.folder.template
    if not folder_template.allow_custom_filename:
        raise ValidationError("This folder does not allow custom file names.")
    label = (new_display_name or "").strip()
    if not label:
        raise ValidationError("Enter a file name.")
    ext = _file_extension(doc.generated_filename)
    generated = build_plain_display_filename(
        user_label=label,
        extension=ext,
        sanitize=_sanitize_filename_part,
    )
    generated = _ensure_unique_generated_filename(
        client=doc.client,
        folder=doc.folder,
        generated=generated,
        exclude_pk=doc.pk,
    )
    old_label = doc.generated_filename
    doc.generated_filename = generated
    doc.save(update_fields=["generated_filename"])
    log_client_activity(
        client=doc.client,
        user=user,
        category=ClientActivityLog.CATEGORY_CLIENT,
        activity=f"Document renamed: {old_label} → {generated}.",
        metadata={"document_id": doc.pk, "old_filename": old_label, "new_filename": generated},
    )
    return doc


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


def folder_upload_meta_json(client: Client) -> dict[str, dict]:
    """Per client folder pk: whether custom names are used and default type id."""
    meta: dict[str, dict] = {}
    for folder in ClientDocumentFolder.objects.filter(client=client).select_related("template"):
        template = folder.template
        default_type = default_document_type_for_folder(folder)
        meta[str(folder.pk)] = {
            "allow_custom_filename": template.allow_custom_filename,
            "default_type_id": default_type.pk if default_type else None,
            "slug": template.slug,
        }
    return meta
