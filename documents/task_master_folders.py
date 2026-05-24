"""Auto-create document folders when task masters are created."""

from __future__ import annotations

from django.utils.text import slugify

from .models import DocumentFolderTemplate, TaskMasterDocumentMapping


def _unique_folder_slug(name: str, *, exclude_folder_id: int | None = None) -> str:
    base = slugify(name)[:70] or "folder"
    slug = base
    n = 2
    qs = DocumentFolderTemplate.objects.all()
    if exclude_folder_id:
        qs = qs.exclude(pk=exclude_folder_id)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{n}"[:80]
        n += 1
    return slug


def provision_task_master_document_folder(task_master, *, user=None) -> DocumentFolderTemplate:
    """
    Create a document folder named like the task master and link the task type to it.
    Idempotent: returns the existing folder if already provisioned.
    """
    existing = DocumentFolderTemplate.objects.filter(task_master=task_master).first()
    if existing:
        TaskMasterDocumentMapping.objects.get_or_create(
            task_master=task_master,
            folder=existing,
        )
        return existing

    folder = DocumentFolderTemplate.objects.create(
        name=task_master.name,
        slug=_unique_folder_slug(task_master.name),
        sort_order=100,
        is_active=True,
        task_master=task_master,
    )
    TaskMasterDocumentMapping.objects.get_or_create(
        task_master=task_master,
        folder=folder,
    )
    return folder


def sync_task_master_folder_name(task_master) -> None:
    """Keep auto-created folder display name in sync when the task master is renamed."""
    folder = DocumentFolderTemplate.objects.filter(task_master=task_master).first()
    if not folder:
        return
    new_name = (task_master.name or "").strip()
    if new_name and folder.name != new_name:
        folder.name = new_name
        folder.save(update_fields=["name"])
