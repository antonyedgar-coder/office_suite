"""Upload and list documents in the context of a task."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from masters.models import Client

from .models import (
    ClientDocument,
    ClientDocumentFolder,
    DocumentTypeTemplate,
    TaskMasterDocumentMapping,
)
from .services import create_client_document_folders, existing_folder_template_ids, save_client_document
from .task_bridge import document_period_from_task, task_allows_document_changes

from tasks.models import Task


def mappings_for_task_master(task_master_id: int):
    return (
        TaskMasterDocumentMapping.objects.filter(
            task_master_id=task_master_id,
            document_type__is_active=True,
            document_type__folder__is_active=True,
        )
        .select_related("document_type", "document_type__folder", "task_master")
        .order_by("sort_order", "document_type__sort_order", "document_type__name")
    )


def ensure_client_folder_for_template(client: Client, folder_template_id: int, *, user) -> ClientDocumentFolder:
    if folder_template_id not in existing_folder_template_ids(client):
        create_client_document_folders(client, [folder_template_id], user=user)
    return ClientDocumentFolder.objects.select_related("template").get(
        client=client,
        template_id=folder_template_id,
    )


def build_task_document_slots(task: Task) -> list[dict]:
    """Rows for task detail: expected file types and current uploads."""
    period_key, period_label = document_period_from_task(task)
    can_change = task_allows_document_changes(task)
    slots: list[dict] = []
    for mapping in mappings_for_task_master(task.task_master_id):
        dt = mapping.document_type
        doc = (
            ClientDocument.objects.filter(
                client_id=task.client_id,
                document_type=dt,
                period_key=period_key,
                status=ClientDocument.STATUS_ACTIVE,
            )
            .select_related("document_type", "folder__template", "uploaded_by", "uploaded_by__employee_profile")
            .order_by("-version")
            .first()
        )
        slots.append(
            {
                "mapping": mapping,
                "document_type": dt,
                "folder_name": dt.folder.name,
                "period_key": period_key,
                "period_label": period_label,
                "document": doc,
                "can_upload": can_change,
            }
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
) -> ClientDocument:
    if not task_allows_document_changes(task):
        raise ValidationError(
            "Documents cannot be changed while this task is complete. "
            "Send back for document rework or ask an administrator."
        )
    if not mappings_for_task_master(task.task_master_id).filter(document_type_id=document_type_id).exists():
        raise ValidationError("This file type is not linked to this task type.")

    document_type = DocumentTypeTemplate.objects.select_related("folder").get(
        pk=document_type_id,
        is_active=True,
    )
    client = task.client
    period_key, period_label = document_period_from_task(task)
    folder = ensure_client_folder_for_template(client, document_type.folder_id, user=user)
    return save_client_document(
        client=client,
        folder=folder,
        document_type=document_type,
        period_key=period_key,
        period_label=period_label,
        uploaded_file=uploaded_file,
        user=user,
        task=task,
    )
