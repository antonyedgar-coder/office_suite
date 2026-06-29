from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from .periods import PERIOD_INDIAN_FY, PERIOD_KIND_CHOICES, PERIOD_NONE


def client_document_upload_to(instance: "ClientDocument", filename: str) -> str:
    ext = ""
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
    suffix = f".{ext}" if ext else ""
    folder_slug = instance.folder.template.slug if instance.folder_id else "general"
    return f"clients/{instance.client_id}/{folder_slug}/{uuid.uuid4().hex}{suffix}"


class DocumentFolderTemplate(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    allow_custom_filename = models.BooleanField(
        default=False,
        help_text="When enabled, uploader may choose the file name; FY and period are still appended.",
    )
    task_master = models.OneToOneField(
        "tasks.TaskMaster",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_folder_template",
        help_text="Set when this folder was auto-created from a task master.",
    )
    client_types = models.ManyToManyField(
        "masters.ClientType",
        blank=True,
        related_name="document_folder_templates",
        help_text="Leave empty to allow all client types. Otherwise only these types see this folder.",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "document folder template"
        permissions = [
            ("manage_document_templates", "Can manage document folder and type templates"),
        ]

    def __str__(self) -> str:
        return self.name


class DocumentTypeTemplate(models.Model):
    folder = models.ForeignKey(
        DocumentFolderTemplate,
        on_delete=models.CASCADE,
        related_name="document_types",
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80)
    allowed_extensions = models.CharField(
        max_length=120,
        default="pdf",
        help_text="Comma-separated extensions without dots, e.g. pdf,xlsx",
    )
    period_kind = models.CharField(
        max_length=16,
        choices=PERIOD_KIND_CHOICES,
        default=PERIOD_NONE,
        help_text="Controls which period field appears on upload.",
    )
    name_template = models.CharField(
        max_length=255,
        default="{document_type}-{client_name}",
        help_text="Legacy field; uploads use automatic filenames from period kind.",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["folder__sort_order", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["folder", "slug"],
                name="documents_type_unique_slug_per_folder",
            ),
        ]
        verbose_name = "document type template"

    def __str__(self) -> str:
        return f"{self.folder.name} — {self.name}"

    def allowed_extension_set(self) -> set[str]:
        return {
            p.strip().lower().lstrip(".")
            for p in (self.allowed_extensions or "").split(",")
            if p.strip()
        }

    def allowed_extensions_display(self) -> str:
        from .file_types import format_extension_labels

        return format_extension_labels(self.allowed_extension_set())


class TaskMasterDocumentMapping(models.Model):
    """Links a task type to a document folder; all file types in that folder appear on the task."""

    task_master = models.ForeignKey(
        "tasks.TaskMaster",
        on_delete=models.CASCADE,
        related_name="document_mappings",
    )
    folder = models.ForeignKey(
        DocumentFolderTemplate,
        on_delete=models.CASCADE,
        related_name="task_mappings",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "folder__sort_order", "folder__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["task_master", "folder"],
                name="documents_taskmaster_folder_uniq",
            ),
        ]
        verbose_name = "task document folder mapping"

    def __str__(self) -> str:
        return f"{self.task_master} → {self.folder.name}"


class ClientDocumentFolder(models.Model):
    client = models.ForeignKey(
        "masters.Client",
        on_delete=models.CASCADE,
        related_name="document_folders",
    )
    template = models.ForeignKey(
        DocumentFolderTemplate,
        on_delete=models.PROTECT,
        related_name="client_folders",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client", "template"],
                name="documents_client_folder_unique",
            ),
        ]
        ordering = ["template__sort_order", "template__name"]

    def __str__(self) -> str:
        return f"{self.client_id} — {self.template.name}"


class ClientDocument(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_SUPERSEDED = "superseded"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUPERSEDED, "Superseded"),
    ]

    client = models.ForeignKey(
        "masters.Client",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    folder = models.ForeignKey(
        ClientDocumentFolder,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    document_type = models.ForeignKey(
        DocumentTypeTemplate,
        on_delete=models.PROTECT,
        related_name="uploads",
    )
    period_key = models.CharField(max_length=32, default="once", db_index=True)
    period_label = models.CharField(max_length=64, blank=True)
    financial_year = models.CharField(
        max_length=16,
        blank=True,
        db_index=True,
        help_text="Legacy; Indian FY portion when applicable.",
    )
    file = models.FileField(upload_to=client_document_upload_to)
    generated_filename = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64, db_index=True)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
    )
    original_filename = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="client_documents_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    task = models.ForeignKey(
        "tasks.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linked_documents",
        help_text="When set, document changes may be locked after the task is marked complete.",
    )

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "client document"
        verbose_name_plural = "client documents"
        permissions = [
            (
                "override_task_document_lock",
                "Can change documents linked to a completed task",
            ),
        ]
        indexes = [
            models.Index(fields=["client", "status", "uploaded_at"]),
            models.Index(
                fields=["client", "document_type", "period_key", "status"],
            ),
            models.Index(fields=["task", "status"]),
        ]

    def __str__(self) -> str:
        return self.generated_filename
