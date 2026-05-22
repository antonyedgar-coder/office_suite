import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import documents.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("masters", "0035_masterrequest_subject_and_message"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentFolderTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "document folder template",
                "ordering": ["sort_order", "name"],
                "permissions": [("manage_document_templates", "Can manage document folder and type templates")],
            },
        ),
        migrations.CreateModel(
            name="DocumentTypeTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("slug", models.SlugField(max_length=80)),
                (
                    "allowed_extensions",
                    models.CharField(
                        default="pdf",
                        help_text="Comma-separated extensions without dots, e.g. pdf,xlsx",
                        max_length=120,
                    ),
                ),
                ("requires_financial_year", models.BooleanField(default=False)),
                (
                    "name_template",
                    models.CharField(
                        default="{document_type}-{client_name}_{fy}",
                        help_text="Placeholders: {document_type}, {client_name}, {pan}, {fy}, {client_id}",
                        max_length=255,
                    ),
                ),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "folder",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_types",
                        to="documents.documentfoldertemplate",
                    ),
                ),
            ],
            options={
                "verbose_name": "document type template",
                "ordering": ["folder__sort_order", "sort_order", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="documenttypetemplate",
            constraint=models.UniqueConstraint(
                fields=("folder", "slug"),
                name="documents_type_unique_slug_per_folder",
            ),
        ),
        migrations.CreateModel(
            name="ClientDocumentFolder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_folders",
                        to="masters.client",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="client_folders",
                        to="documents.documentfoldertemplate",
                    ),
                ),
            ],
            options={"ordering": ["template__sort_order", "template__name"]},
        ),
        migrations.AddConstraint(
            model_name="clientdocumentfolder",
            constraint=models.UniqueConstraint(
                fields=("client", "template"),
                name="documents_client_folder_unique",
            ),
        ),
        migrations.CreateModel(
            name="ClientDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("financial_year", models.CharField(blank=True, db_index=True, max_length=16)),
                ("file", models.FileField(upload_to=documents.models.client_document_upload_to)),
                ("generated_filename", models.CharField(max_length=255)),
                ("content_hash", models.CharField(db_index=True, max_length=64)),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("superseded", "Superseded")],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="masters.client",
                    ),
                ),
                (
                    "document_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="uploads",
                        to="documents.documenttypetemplate",
                    ),
                ),
                (
                    "folder",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="documents",
                        to="documents.clientdocumentfolder",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="client_documents_uploaded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-uploaded_at"]},
        ),
        migrations.AddIndex(
            model_name="clientdocument",
            index=models.Index(fields=["client", "status", "uploaded_at"], name="documents_cl_client__a8f4c1_idx"),
        ),
        migrations.AddIndex(
            model_name="clientdocument",
            index=models.Index(
                fields=["client", "document_type", "financial_year", "status"],
                name="documents_cl_client__b2e8d4_idx",
            ),
        ),
    ]
