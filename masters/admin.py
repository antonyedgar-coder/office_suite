from django.contrib import admin
from django.utils import timezone

from .models import (
    Client,
    ClientActivityLog,
    ClientDSC,
    ClientGroup,
    ClientPortalCredential,
    DSCInOut,
    DSCNotification,
    ClientType,
    ExpenseCategory,
    MasterRequest,
    MasterRequestNotification,
    PortalName,
    ClientSequence,
    DirectorMapping,
    GroupSequence,
)


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


@admin.register(ClientActivityLog)
class ClientActivityLogAdmin(admin.ModelAdmin):
    list_display = ("client", "category", "activity", "user", "task", "created_at")
    list_filter = ("category", "created_at")
    search_fields = ("client__client_id", "client__client_name", "activity")
    readonly_fields = (
        "client",
        "user",
        "category",
        "activity",
        "task",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ClientType)
class ClientTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "pan_mandatory",
        "allow_task_submit_without_pan",
        "is_active",
        "sort_order",
    )
    list_filter = ("is_active", "pan_mandatory", "allow_task_submit_without_pan")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(PortalName)
class PortalNameAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(ClientDSC)
class ClientDSCAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "issue_date",
        "expiry_date",
        "expiry_notification",
        "remarks",
        "last_expiry_notification_sent_at",
        "created_by",
        "created_at",
    )
    list_filter = ("expiry_notification", "expiry_date", "issue_date")
    search_fields = ("client__client_id", "client__client_name", "client__pan")
    readonly_fields = ("created_by", "created_at", "updated_by", "updated_at")


@admin.register(DSCNotification)
class DSCNotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "dsc", "is_read", "created_at")
    list_filter = ("is_read", "created_at")
    search_fields = ("user__email", "message", "dsc__client__client_name")
    readonly_fields = ("created_at",)


@admin.register(DSCInOut)
class DSCInOutAdmin(admin.ModelAdmin):
    list_display = ("dsc", "in_date", "out_date", "remarks")
    list_filter = ("in_date", "out_date")
    search_fields = ("dsc__client__client_name", "dsc__client__pan", "remarks")
    raw_id_fields = ("dsc",)


@admin.register(ClientPortalCredential)
class ClientPortalCredentialAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "portal",
        "portal_username",
        "created_by",
        "created_at",
        "updated_by",
        "updated_at",
    )
    list_filter = ("portal", "created_at")
    search_fields = ("client__client_id", "client__client_name", "portal__name", "portal_username")
    readonly_fields = ("created_by", "created_at", "updated_by", "updated_at")


@admin.register(MasterRequest)
class MasterRequestAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "subject",
        "request_type",
        "status",
        "requested_by",
        "assigned_to",
        "client",
        "created_at",
    )
    list_filter = ("request_type", "status", "created_at")
    search_fields = (
        "subject",
        "message",
        "requested_by__username",
        "assigned_to__username",
        "client__client_name",
    )
    readonly_fields = ("created_at", "updated_at", "completed_at")


@admin.register(MasterRequestNotification)
class MasterRequestNotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "master_request", "is_read", "created_at")
    list_filter = ("kind", "is_read")

