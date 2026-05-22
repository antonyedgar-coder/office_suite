from django.db import migrations


def grant_delete_document_permission(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    doc_ct = ContentType.objects.filter(app_label="documents", model="clientdocument").first()
    if not doc_ct:
        return
    delete_perm = Permission.objects.filter(
        content_type=doc_ct,
        codename="delete_clientdocument",
    ).first()
    add_perm = Permission.objects.filter(
        content_type=doc_ct,
        codename="add_clientdocument",
    ).first()
    if not delete_perm or not add_perm:
        return
    for group in Group.objects.filter(permissions=add_perm):
        group.permissions.add(delete_perm)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0007_rename_documents_cl_client__a8f4c1_idx_documents_c_client__670b56_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(grant_delete_document_permission, noop),
    ]
