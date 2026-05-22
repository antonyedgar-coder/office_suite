from django.db import migrations, models


def link_all_client_types(apps, schema_editor):
    DocumentFolderTemplate = apps.get_model("documents", "DocumentFolderTemplate")
    ClientType = apps.get_model("masters", "ClientType")
    types = list(ClientType.objects.filter(is_active=True))
    if not types:
        return
    for folder in DocumentFolderTemplate.objects.all():
        folder.client_types.set(types)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0035_masterrequest_subject_and_message"),
        ("documents", "0004_grant_manage_document_templates"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentfoldertemplate",
            name="client_types",
            field=models.ManyToManyField(
                blank=True,
                help_text="Leave empty to allow all client types. Otherwise only these types see this folder.",
                related_name="document_folder_templates",
                to="masters.clienttype",
            ),
        ),
        migrations.RunPython(link_all_client_types, noop),
    ]
