"""Upload and list documents in the context of a task."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from masters.models import Client

from .folder_constants import SUPPORTING_DOCUMENTS_SLUG
from .models import (
    ClientDocument,
    ClientDocumentFolder,
    DocumentTypeTemplate,
    TaskMasterDocumentMapping,
)
from .services import create_client_document_folders, existing_folder_template_ids, save_client_document
from .task_bridge import document_period_from_task, task_allows_document_upload

from tasks.models import Task


def mappings_for_task_master(task_master_id: int):
    return (
        TaskMasterDocumentMapping.objects.filter(
            task_master_id=task_master_id,
            folder__is_active=True,
        )
        .select_related("folder", "task_master")
        .order_by("sort_order", "folder__sort_order", "folder__name")
    )


def mapped_folder_ids_for_task_master(task_master_id: int) -> set[int]:
    return set(mappings_for_task_master(task_master_id).values_list("folder_id", flat=True))


def ensure_client_folder_for_template(client: Client, folder_template_id: int, *, user) -> ClientDocumentFolder:
    if folder_template_id not in existing_folder_template_ids(client):
        create_client_document_folders(client, [folder_template_id], user=user)
    return ClientDocumentFolder.objects.select_related("template").get(
        client=client,
        template_id=folder_template_id,
    )


def _supporting_document_type() -> DocumentTypeTemplate | None:
    return (
        DocumentTypeTemplate.objects.select_related("folder")
        .filter(
            folder__slug=SUPPORTING_DOCUMENTS_SLUG,
            folder__is_active=True,
            is_active=True,
        )
        .order_by("sort_order", "name")
        .first()
    )


def _slot_base(
    *,
    mapping: TaskMasterDocumentMapping | None,
    document_type: DocumentTypeTemplate,
    period_key: str,
    period_label: str,
    task: Task,
) -> dict:
    folder = document_type.folder
    folder_slug = folder.slug
    return {
        "mapping": mapping,
        "document_type": document_type,
        "folder_name": folder.name,
        "period_key": period_key,
        "period_label": period_label,
        "can_upload": task_allows_document_upload(task, folder_slug=folder_slug),
        "allow_custom_filename": folder.allow_custom_filename,
        "folder_slug": folder_slug,
    }


def _append_slots_for_document_type(
    slots: list[dict],
    *,
    mapping: TaskMasterDocumentMapping | None,
    document_type: DocumentTypeTemplate,
    period_key: str,
    period_label: str,
    task: Task,
) -> None:
    base = _slot_base(
        mapping=mapping,
        document_type=document_type,
        period_key=period_key,
        period_label=period_label,
        task=task,
    )
    if document_type.folder.allow_custom_filename:
        docs = list(
            ClientDocument.objects.filter(
                client_id=task.client_id,
                document_type=document_type,
                period_key=period_key,
                status=ClientDocument.STATUS_ACTIVE,
                task_id=task.pk,
            )
            .select_related("document_type", "folder__template", "uploaded_by", "uploaded_by__employee_profile")
            .order_by("-uploaded_at", "-pk")
        )
        if docs:
            for doc in docs:
                slots.append({**base, "document": doc, "upload_only": False})
        else:
            slots.append({**base, "document": None, "upload_only": False})
        if base["can_upload"]:
            slots.append({**base, "document": None, "upload_only": True})
        return

    doc = (
        ClientDocument.objects.filter(
            client_id=task.client_id,
            document_type=document_type,
            period_key=period_key,
            status=ClientDocument.STATUS_ACTIVE,
        )
        .select_related("document_type", "folder__template", "uploaded_by", "uploaded_by__employee_profile")
        .order_by("-version")
        .first()
    )
    slots.append({**base, "document": doc, "upload_only": False})


def build_task_document_slots(task: Task) -> list[dict]:
    """Rows for task detail: all file types in folders linked to this task type."""
    period_key, period_label = document_period_from_task(task)
    slots: list[dict] = []
    seen_supporting = False

    for mapping in mappings_for_task_master(task.task_master_id):
        folder = mapping.folder
        if folder.slug == SUPPORTING_DOCUMENTS_SLUG:
            seen_supporting = True
        doc_types = folder.document_types.filter(is_active=True).order_by("sort_order", "name")
        for document_type in doc_types:
            _append_slots_for_document_type(
                slots,
                mapping=mapping,
                document_type=document_type,
                period_key=period_key,
                period_label=period_label,
                task=task,
            )

    if not seen_supporting:
        supporting_type = _supporting_document_type()
        if supporting_type and task_allows_document_upload(task, folder_slug=SUPPORTING_DOCUMENTS_SLUG):
            _append_slots_for_document_type(
                slots,
                mapping=None,
                document_type=supporting_type,
                period_key=period_key,
                period_label=period_label,
                task=task,
            )

    return slots


def task_linked_documents(task: Task):
    return (
        ClientDocument.objects.filter(
            task_id=task.pk,
            status=ClientDocument.STATUS_ACTIVE,
        )
        .select_related("document_type", "folder__template", "uploaded_by", "uploaded_by__employee_profile")
        .order_by("document_type__sort_order", "-version")
    )


@transaction.atomic
def upload_document_for_task(
    task: Task,
    *,
    document_type_id: int,
    uploaded_file,
    user,
    custom_display_name: str = "",
) -> ClientDocument:
    document_type = DocumentTypeTemplate.objects.select_related("folder").get(
        pk=document_type_id,
        is_active=True,
    )
    folder = document_type.folder
    if not task_allows_document_upload(task, folder_slug=folder.slug):
        if task.status == Task.STATUS_PENDING_ASSIGNMENT:
            raise ValidationError(
                "Documents for this task can be uploaded only after assignees approve the task, "
                "except Supporting Documents and KYC Documents."
            )
        raise ValidationError(
            "Documents cannot be changed while this task is complete. "
            "Send back for document rework or ask an administrator."
        )

    mapped_folder_ids = mapped_folder_ids_for_task_master(task.task_master_id)
    if folder.pk not in mapped_folder_ids and folder.slug != SUPPORTING_DOCUMENTS_SLUG:
        raise ValidationError("This folder is not linked to this task type.")

    client = task.client
    period_key, period_label = document_period_from_task(task)
    client_folder = ensure_client_folder_for_template(client, folder.pk, user=user)
    return save_client_document(
        client=client,
        folder=client_folder,
        document_type=document_type,
        period_key=period_key,
        period_label=period_label,
        uploaded_file=uploaded_file,
        user=user,
        task=task,
        custom_display_name=custom_display_name,
    )
