from django.db import migrations, models
from django.utils.text import slugify


def _unique_slug(name, Folder, exclude_pk=None):
    base = slugify(name)[:70] or "folder"
    slug = base
    n = 2
    while True:
        qs = Folder.objects.filter(slug=slug)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return slug
        slug = f"{base}-{n}"[:80]
        n += 1


def migrate_existing_mappings_to_folders(apps, schema_editor):
    """Copy folder from each linked file type onto the mapping row."""
    Mapping = apps.get_model("documents", "TaskMasterDocumentMapping")
    DocumentType = apps.get_model("documents", "DocumentTypeTemplate")

    seen = set()
    for mapping in Mapping.objects.all().order_by("pk"):
        doc_type = DocumentType.objects.filter(pk=mapping.document_type_id).first()
        if not doc_type:
            mapping.delete()
            continue
        folder_id = doc_type.folder_id
        key = (mapping.task_master_id, folder_id)
        if key in seen:
            mapping.delete()
            continue
        mapping.folder_id = folder_id
        mapping.save(update_fields=["folder_id"])
        seen.add(key)


def provision_task_master_folders(apps, schema_editor):
    """Create a folder per task master after document_type column is removed."""
    Mapping = apps.get_model("documents", "TaskMasterDocumentMapping")
    Folder = apps.get_model("documents", "DocumentFolderTemplate")
    TaskMaster = apps.get_model("tasks", "TaskMaster")

    for master in TaskMaster.objects.all():
        if Folder.objects.filter(task_master_id=master.pk).exists():
            continue
        folder = Folder.objects.create(
            name=master.name,
            slug=_unique_slug(master.name, Folder),
            sort_order=100,
            is_active=True,
            task_master_id=master.pk,
            allow_custom_filename=False,
        )
        Mapping.objects.get_or_create(task_master_id=master.pk, folder_id=folder.pk)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    # PostgreSQL cannot ALTER a table in the same transaction after RunPython
    # has updated rows on it ("pending trigger events"). Commit each step.
    atomic = False

    dependencies = [
        ("documents", "0012_standard_client_folders"),
        ("tasks", "0014_alter_task_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentfoldertemplate",
            name="task_master",
            field=models.OneToOneField(
                blank=True,
                help_text="Set when this folder was auto-created from a task master.",
                null=True,
                on_delete=models.SET_NULL,
                related_name="document_folder_template",
                to="tasks.taskmaster",
            ),
        ),
        migrations.AddField(
            model_name="taskmasterdocumentmapping",
            name="folder",
            field=models.ForeignKey(
                null=True,
                on_delete=models.CASCADE,
                related_name="task_mappings",
                to="documents.documentfoldertemplate",
            ),
        ),
        migrations.RunPython(migrate_existing_mappings_to_folders, noop),
        migrations.RemoveConstraint(
            model_name="taskmasterdocumentmapping",
            name="documents_taskmaster_doctype_uniq",
        ),
        migrations.RemoveField(
            model_name="taskmasterdocumentmapping",
            name="document_type",
        ),
        migrations.AlterField(
            model_name="taskmasterdocumentmapping",
            name="folder",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="task_mappings",
                to="documents.documentfoldertemplate",
            ),
        ),
        migrations.RunPython(provision_task_master_folders, noop),
        migrations.AddConstraint(
            model_name="taskmasterdocumentmapping",
            constraint=models.UniqueConstraint(
                fields=("task_master", "folder"),
                name="documents_taskmaster_folder_uniq",
            ),
        ),
        migrations.AlterModelOptions(
            name="taskmasterdocumentmapping",
            options={
                "ordering": ["sort_order", "folder__sort_order", "folder__name"],
                "verbose_name": "task document folder mapping",
            },
        ),
    ]
