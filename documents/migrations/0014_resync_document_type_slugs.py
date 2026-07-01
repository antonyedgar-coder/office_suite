# Sync document type slugs from display names after renames left stale slugs.

from django.db import migrations
from django.utils.text import slugify


def resync_document_type_slugs(apps, schema_editor):
    DocumentTypeTemplate = apps.get_model("documents", "DocumentTypeTemplate")
    rows = list(
        DocumentTypeTemplate.objects.all().order_by("folder_id", "pk").values("pk", "folder_id", "name", "slug")
    )
    used_by_folder: dict[int, set[str]] = {}
    for row in rows:
        folder_id = row["folder_id"]
        used = used_by_folder.setdefault(folder_id, set())
        base = slugify(row["name"] or "")[:80] or "file"
        slug = base
        n = 2
        while slug in used:
            suffix = f"-{n}"
            slug = f"{base[: 80 - len(suffix)]}{suffix}"
            n += 1
        used.add(slug)
        if row["slug"] != slug:
            DocumentTypeTemplate.objects.filter(pk=row["pk"]).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0013_task_folder_mapping"),
    ]

    operations = [
        migrations.RunPython(resync_document_type_slugs, migrations.RunPython.noop),
    ]
