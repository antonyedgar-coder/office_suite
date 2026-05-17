from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.task_dashboard, name="task_dashboard"),
    path("groups/", views.task_group_list, name="task_group_list"),
    path("groups/new/", views.task_group_create, name="task_group_create"),
    path("groups/<int:pk>/", views.task_group_edit, name="task_group_edit"),
    path("masters/", views.task_master_list, name="task_master_list"),
    path("masters/new/", views.task_master_create, name="task_master_create"),
    path("masters/<int:pk>/", views.task_master_edit, name="task_master_edit"),
    path("export.csv", views.task_list_csv, name="task_list_csv"),
    path("report/export.csv", views.task_report_csv, name="task_report_csv"),
    path("report/", views.task_report, name="task_report"),
    path("", views.task_list, name="task_list"),
    path("my/export.csv", views.task_my_list_csv, name="task_my_list_csv"),
    path("my/", views.task_my_list, name="task_my_list"),
    path("new/", views.task_create, name="task_create"),
    path("verify/", views.task_verify_queue, name="task_verify_queue"),
    path("verify/<int:pk>/approve/", views.task_verify_approve, name="task_verify_approve"),
    path("verify/<int:pk>/rework/", views.task_verify_rework, name="task_verify_rework"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
    path("<int:pk>/", views.task_detail, name="task_detail"),
]
