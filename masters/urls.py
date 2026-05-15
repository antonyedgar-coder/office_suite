from django.urls import path

from . import views


urlpatterns = [
    path("clients/", views.client_list, name="client_list"),
    path("clients/pending/", views.client_pending_list, name="client_pending_list"),
    path("clients/new/", views.client_create, name="client_create"),
    path("clients/import/", views.client_import, name="client_import"),
    path("clients/import/template/", views.client_import_template, name="client_import_template"),
    path("groups/", views.client_group_list, name="client_group_list"),
    path("groups/bulk-upload/", views.client_group_bulk_import, name="client_group_bulk_import"),
    path(
        "groups/bulk-upload/template/",
        views.client_group_bulk_import_template,
        name="client_group_bulk_import_template",
    ),
    path("groups/new/", views.client_group_create, name="client_group_create"),
    path("groups/<int:pk>/delete/", views.client_group_delete, name="client_group_delete"),
    path("groups/<int:pk>/", views.client_group_edit, name="client_group_edit"),
    path("clients/<str:client_id>/approve/", views.client_approve, name="client_approve"),
    path("clients/<str:client_id>/delete/", views.client_delete, name="client_delete"),
    path("clients/<str:client_id>/", views.client_edit, name="client_edit"),
    path("directors/", views.director_list, name="director_list"),
    path("directors/new/", views.director_create, name="director_create"),
    path("directors/<int:pk>/delete/", views.director_delete, name="director_delete"),
    path("directors/<int:pk>/", views.director_edit, name="director_edit"),
    path("directors/bulk-upload/", views.director_mapping_bulk_import, name="director_mapping_bulk_import"),
    path(
        "directors/bulk-upload/template/",
        views.director_mapping_bulk_import_template,
        name="director_mapping_bulk_import_template",
    ),
]

