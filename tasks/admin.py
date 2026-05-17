from django.contrib import admin

from .models import (
    Task,
    TaskActivity,
    TaskAssignment,
    TaskEnrollmentAssignee,
    TaskGroup,
    TaskMaster,
    TaskNotification,
    TaskRecurrenceEnrollment,
)


class TaskEnrollmentAssigneeInline(admin.TabularInline):
    model = TaskEnrollmentAssignee
    extra = 0


@admin.register(TaskGroup)
class TaskGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(TaskMaster)
class TaskMasterAdmin(admin.ModelAdmin):
    list_display = ("name", "task_group", "is_recurring", "frequency", "is_active")
    list_filter = ("task_group", "is_recurring", "frequency", "is_active")
    search_fields = ("name",)


@admin.register(TaskRecurrenceEnrollment)
class TaskRecurrenceEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("client", "task_master", "verifier", "is_active", "is_paused", "started_at")
    list_filter = ("is_active", "is_paused")
    inlines = [TaskEnrollmentAssigneeInline]


class TaskAssignmentInline(admin.TabularInline):
    model = TaskAssignment
    extra = 0


class TaskActivityInline(admin.TabularInline):
    model = TaskActivity
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "display_title",
        "client",
        "task_master",
        "status",
        "due_date",
        "period_key",
        "submitted_at",
        "approved_at",
        "auto_created",
    )
    list_filter = ("status", "auto_created", "period_type", "task_master__task_group")
    search_fields = ("title", "client__client_id", "period_key")
    inlines = [TaskAssignmentInline, TaskActivityInline]


@admin.register(TaskNotification)
class TaskNotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "is_read", "created_at")
    list_filter = ("kind", "is_read")
