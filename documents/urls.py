from django.urls import path

from . import views

urlpatterns = [
    path("files/", views.document_file_list, name="document_file_list"),
    path(
        "settings/task-links/",
        views.task_document_mapping_list,
        name="task_document_mapping_list",
    ),
    path("create-folder/", views.client_folder_create, name="client_folder_create"),
    path("upload/", views.client_document_upload_pick, name="client_document_upload_pick"),
    path(
        "settings/folders/",
        views.document_folder_template_list,
        name="document_folder_template_list",
    ),
    path(
        "settings/folders/new/",
        views.document_folder_template_create,
        name="document_folder_template_create",
    ),
    path(
        "settings/folders/<int:pk>/edit/",
        views.document_folder_template_edit,
        name="document_folder_template_edit",
    ),
    path(
        "settings/folders/<int:pk>/delete/",
        views.document_folder_template_delete,
        name="document_folder_template_delete",
    ),
    path(
        "settings/file-types/",
        views.document_type_template_list,
        name="document_type_template_list",
    ),
    path(
        "settings/file-types/new/",
        views.document_type_template_create,
        name="document_type_template_create",
    ),
    path(
        "settings/file-types/<int:pk>/edit/",
        views.document_type_template_edit,
        name="document_type_template_edit",
    ),
    path(
        "clients/<str:client_id>/upload/",
        views.client_document_upload,
        name="client_document_upload",
    ),
    path(
        "<int:pk>/replace/",
        views.client_document_replace,
        name="client_document_replace",
    ),
    path(
        "<int:pk>/rename/",
        views.client_document_rename,
        name="client_document_rename",
    ),
    path(
        "<int:pk>/view/",
        views.client_document_view,
        name="client_document_view",
    ),
    path(
        "<int:pk>/download/",
        views.client_document_download,
        name="client_document_download",
    ),
    path(
        "<int:pk>/delete/",
        views.client_document_delete,
        name="client_document_delete",
    ),
]
