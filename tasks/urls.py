from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.task_dashboard, name="task_dashboard"),
    path("groups/", views.task_group_list, name="task_group_list"),
    path("groups/bulk-upload/", views.task_group_bulk_import, name="task_group_bulk_import"),
    path(
        "groups/bulk-upload/template/",
        views.task_group_bulk_import_template,
        name="task_group_bulk_import_template",
    ),
    path("groups/new/", views.task_group_create, name="task_group_create"),
    path("groups/<int:pk>/delete/", views.task_group_delete, name="task_group_delete"),
    path("groups/<int:pk>/", views.task_group_edit, name="task_group_edit"),
    path("masters/", views.task_master_list, name="task_master_list"),
    path("masters/bulk-upload/", views.task_master_bulk_import, name="task_master_bulk_import"),
    path(
        "masters/bulk-upload/template/",
        views.task_master_bulk_import_template,
        name="task_master_bulk_import_template",
    ),
    path("masters/new/", views.task_master_create, name="task_master_create"),
    path("masters/quick-create/", views.task_master_quick_create_api, name="task_master_quick_create_api"),
    path("masters/<int:pk>/delete/", views.task_master_delete, name="task_master_delete"),
    path("masters/<int:pk>/", views.task_master_edit, name="task_master_edit"),
    path("export.csv", views.task_list_csv, name="task_list_csv"),
    path("report/export.csv", views.task_report_csv, name="task_report_csv"),
    path("report/", views.task_report, name="task_report"),
    path("", views.task_list, name="task_list"),
    path("my/export.csv", views.task_my_list_csv, name="task_my_list_csv"),
    path("my/", views.task_my_list, name="task_my_list"),
    path("new/", views.task_create, name="task_create"),
    path("new/bulk-upload/", views.task_bulk_import, name="task_bulk_import"),
    path(
        "new/bulk-upload/template/",
        views.task_bulk_import_template,
        name="task_bulk_import_template",
    ),
    path("verify/", views.task_verify_queue, name="task_verify_queue"),
    path(
        "verify/<int:pk>/approve-assignment/",
        views.task_assignment_approve,
        name="task_assignment_approve",
    ),
    path("verify/<int:pk>/approve/", views.task_verify_approve, name="task_verify_approve"),
    path("verify/<int:pk>/rework/", views.task_verify_rework, name="task_verify_rework"),
    path("document-check/", views.task_document_check_queue, name="task_document_check_queue"),
    path(
        "document-check/<int:pk>/complete/",
        views.task_document_check_complete,
        name="task_document_check_complete",
    ),
    path(
        "document-check/<int:pk>/send-back/",
        views.task_document_check_send_back,
        name="task_document_check_send_back",
    ),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
    path("<int:pk>/edit/", views.task_edit, name="task_edit"),
    path("<int:pk>/", views.task_detail, name="task_detail"),
]
