from django.db import migrations, models
import django.db.models.deletion


def grant_override_lock_permission(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    doc_ct = ContentType.objects.filter(app_label="documents", model="clientdocument").first()
    if not doc_ct:
        return
    override = Permission.objects.filter(
        content_type=doc_ct,
        codename="override_task_document_lock",
    ).first()
    if not override:
        return
    for group in Group.objects.filter(name__iregex=r"admin|administrator|super"):
        group.permissions.add(override)
    for group in Group.objects.filter(permissions__codename="manage_document_templates").distinct():
        group.permissions.add(override)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0008_grant_delete_clientdocument"),
        ("tasks", "0010_task_document_rework_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskMasterDocumentMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "document_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="task_mappings",
                        to="documents.documenttypetemplate",
                    ),
                ),
                (
                    "task_master",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_mappings",
                        to="tasks.taskmaster",
                    ),
                ),
            ],
            options={
                "verbose_name": "task document mapping",
                "ordering": ["sort_order", "document_type__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="taskmasterdocumentmapping",
            constraint=models.UniqueConstraint(
                fields=("task_master", "document_type"),
                name="documents_taskmaster_doctype_uniq",
            ),
        ),
        migrations.AddField(
            model_name="clientdocument",
            name="task",
            field=models.ForeignKey(
                blank=True,
                help_text="When set, document changes may be locked after the task is marked complete.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="linked_documents",
                to="tasks.task",
            ),
        ),
        migrations.AddIndex(
            model_name="clientdocument",
            index=models.Index(fields=["task", "status"], name="documents_c_task_id_status_idx"),
        ),
        migrations.AlterModelOptions(
            name="clientdocument",
            options={
                "ordering": ["-uploaded_at"],
                "permissions": [
                    (
                        "override_task_document_lock",
                        "Can change documents linked to a completed task",
                    ),
                ],
            },
        ),
        migrations.RunPython(grant_override_lock_permission, noop),
    ]
