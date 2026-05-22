from django.contrib import admin

from .models import (
    ClientDocument,
    ClientDocumentFolder,
    DocumentFolderTemplate,
    DocumentTypeTemplate,
    TaskMasterDocumentMapping,
)


class DocumentTypeTemplateInline(admin.TabularInline):
    model = DocumentTypeTemplate
    extra = 0
    fields = (
        "name",
        "slug",
        "allowed_extensions",
        "period_kind",
        "name_template",
        "sort_order",
        "is_active",
    )


@admin.register(DocumentFolderTemplate)
class DocumentFolderTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order", "is_active")
    list_filter = ("is_active", "client_types")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("client_types",)
    inlines = [DocumentTypeTemplateInline]


@admin.register(DocumentTypeTemplate)
class DocumentTypeTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "folder", "slug", "period_kind", "sort_order", "is_active")
    list_filter = ("folder", "is_active", "period_kind")
    search_fields = ("name", "slug", "folder__name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(TaskMasterDocumentMapping)
class TaskMasterDocumentMappingAdmin(admin.ModelAdmin):
    list_display = ("task_master", "document_type", "sort_order")
    list_filter = ("task_master__task_group",)
    autocomplete_fields = ("task_master", "document_type")


@admin.register(ClientDocumentFolder)
class ClientDocumentFolderAdmin(admin.ModelAdmin):
    list_display = ("client", "template", "created_at")
    list_filter = ("template",)
    search_fields = ("client__client_id", "client__client_name")


@admin.register(ClientDocument)
class ClientDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "generated_filename",
        "client",
        "document_type",
        "task",
        "period_label",
        "financial_year",
        "version",
        "status",
        "uploaded_at",
    )
    list_filter = ("status", "document_type__folder")
    search_fields = ("client__client_id", "generated_filename", "content_hash")
    readonly_fields = ("content_hash", "uploaded_at")
