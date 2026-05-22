from django.db import migrations


def grant_document_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    doc_ct = ContentType.objects.filter(app_label="documents", model="clientdocument").first()
    if not doc_ct:
        return
    doc_perms = list(
        Permission.objects.filter(
            content_type=doc_ct,
            codename__in=("view_clientdocument", "add_clientdocument"),
        )
    )
    if not doc_perms:
        return

    view_client_ct = ContentType.objects.filter(app_label="masters", model="client").first()
    if not view_client_ct:
        return
    view_client_perm = Permission.objects.filter(
        content_type=view_client_ct,
        codename="view_client",
    ).first()
    if not view_client_perm:
        return

    tmpl_ct = ContentType.objects.filter(app_label="documents", model="documentfoldertemplate").first()
    tmpl_perm = None
    if tmpl_ct:
        tmpl_perm = Permission.objects.filter(
            content_type=tmpl_ct,
            codename="manage_document_templates",
        ).first()

    for group in Group.objects.filter(permissions=view_client_perm):
        group.permissions.add(*doc_perms)
        if tmpl_perm and (group.name or "").lower() in ("admin", "administrator", "super admin"):
            group.permissions.add(tmpl_perm)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_seed_document_templates"),
    ]

    operations = [
        migrations.RunPython(grant_document_permissions, noop),
    ]
