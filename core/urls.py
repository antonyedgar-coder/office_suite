from django.urls import path

from . import employee_views, group_views, views as core_views

urlpatterns = [
    path("", core_views.dashboard_view, name="dashboard"),
    path("activity-log/download.csv", core_views.activity_log_csv, name="activity_log_csv"),
    path("activity-log/", core_views.activity_log_list, name="activity_log"),
    path("admin-tools/reset-test-data/", core_views.reset_test_data, name="reset_test_data"),
    path("users/", employee_views.employee_list, name="user_list"),
    path("users/new/", employee_views.employee_create, name="user_create"),
    path("users/<int:pk>/", employee_views.employee_edit, name="user_edit"),
    path("account/first-password/", employee_views.first_password_change, name="first_password_change"),
    path("users/groups/", group_views.group_list, name="user_group_list"),
    path("users/groups/new/", group_views.group_create, name="user_group_create"),
    path("users/groups/<int:pk>/", group_views.group_edit, name="user_group_edit"),
    path("users/groups/<int:pk>/delete/", group_views.group_delete, name="user_group_delete"),
]
