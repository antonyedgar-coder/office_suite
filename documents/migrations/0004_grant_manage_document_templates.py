from django.db import migrations


def grant_manage_templates(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    tmpl_ct = ContentType.objects.filter(app_label="documents", model="documentfoldertemplate").first()
    if not tmpl_ct:
        return
    manage_perm = Permission.objects.filter(
        content_type=tmpl_ct,
        codename="manage_document_templates",
    ).first()
    if not manage_perm:
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

    for group in Group.objects.filter(permissions=view_client_perm):
        group.permissions.add(manage_perm)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_grant_document_perms"),
    ]

    operations = [
        migrations.RunPython(grant_manage_templates, noop),
    ]
