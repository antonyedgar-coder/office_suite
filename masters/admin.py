from django.contrib import admin
from django.utils import timezone

from .models import Client, ClientGroup, ClientSequence, DirectorMapping, GroupSequence


@admin.register(GroupSequence)
class GroupSequenceAdmin(admin.ModelAdmin):
    list_display = ("letter", "last_value")


@admin.register(ClientGroup)
class ClientGroupAdmin(admin.ModelAdmin):
    list_display = ("group_id", "name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("group_id", "name", "notes")
    readonly_fields = ("group_id", "created_at", "updated_at")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        "client_id",
        "client_name",
        "client_group",
        "file_no",
        "client_type",
        "branch",
        "dob",
        "approval_status",
        "created_by",
        "approved_by",
        "approved_at",
        "pan",
        "passport_no",
    )
    search_fields = ("client_id", "client_name", "pan", "passport_no", "aadhaar_no", "client_group__name", "client_group__group_id")
    list_filter = ("client_type", "branch", "approval_status")
    readonly_fields = ("client_id", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if request.user.is_superuser:
            now = timezone.now()
            obj.approval_status = Client.APPROVED
            obj.approved_by = request.user
            obj.approved_at = now
            if not obj.created_by_id:
                obj.created_by = request.user
        else:
            obj.approval_status = Client.PENDING
            obj.approved_by = None
            obj.approved_at = None
            if not change:
                obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(DirectorMapping)
class DirectorMappingAdmin(admin.ModelAdmin):
    list_display = ("director", "company", "appointed_date", "cessation_date", "reason_for_cessation")
    list_select_related = ("director", "company")
    search_fields = ("director__client_name", "director__din", "company__client_name", "company__client_id")
    list_filter = ("appointed_date",)


@admin.register(ClientSequence)
class ClientSequenceAdmin(admin.ModelAdmin):
    list_display = ("prefix", "last_value")

