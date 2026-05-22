"""Grant master request permissions to groups that can view clients."""

from django.db import migrations


def grant_master_request_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.filter(app_label="masters", model="masterrequest").first()
    if not ct:
        return
    perms = list(
        Permission.objects.filter(
            content_type=ct,
            codename__in=("add_masterrequest", "view_masterrequest"),
        )
    )
    if not perms:
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
        group.permissions.add(*perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0031_master_request"),
    ]

    operations = [
        migrations.RunPython(grant_master_request_permissions, noop),
    ]
