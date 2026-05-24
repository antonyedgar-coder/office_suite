from django.db import migrations, models


def ensure_standard_folders(apps, schema_editor):
    DocumentFolderTemplate = apps.get_model("documents", "DocumentFolderTemplate")
    DocumentTypeTemplate = apps.get_model("documents", "DocumentTypeTemplate")
    Client = apps.get_model("masters", "Client")
    ClientDocumentFolder = apps.get_model("documents", "ClientDocumentFolder")

    supporting, _ = DocumentFolderTemplate.objects.update_or_create(
        slug="supporting-documents",
        defaults={
            "name": "Supporting Documents",
            "sort_order": 5,
            "is_active": True,
            "allow_custom_filename": True,
        },
    )
    kyc = DocumentFolderTemplate.objects.filter(slug="kyc").first()
    if kyc:
        kyc.name = "KYC Documents"
        kyc.slug = "kyc-documents"
        kyc.sort_order = 6
        kyc.is_active = True
        kyc.allow_custom_filename = False
        kyc.save()
    else:
        kyc, _ = DocumentFolderTemplate.objects.update_or_create(
            slug="kyc-documents",
            defaults={
                "name": "KYC Documents",
                "sort_order": 6,
                "is_active": True,
                "allow_custom_filename": False,
            },
        )

    DocumentTypeTemplate.objects.get_or_create(
        folder=supporting,
        slug="supporting-file",
        defaults={
            "name": "Supporting file",
            "allowed_extensions": "pdf,jpg,jpeg,png,xlsx,xls,doc,docx",
            "period_kind": "none",
            "sort_order": 10,
            "is_active": True,
        },
    )
    DocumentTypeTemplate.objects.get_or_create(
        folder=kyc,
        slug="kyc-file",
        defaults={
            "name": "KYC file",
            "allowed_extensions": "pdf,jpg,jpeg,png",
            "period_kind": "none",
            "sort_order": 10,
            "is_active": True,
        },
    )

    for client_id in Client.objects.values_list("pk", flat=True):
        for tmpl in (supporting, kyc):
            ClientDocumentFolder.objects.get_or_create(client_id=client_id, template=tmpl)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0011_alter_clientdocument_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentfoldertemplate",
            name="allow_custom_filename",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, uploader may choose the file name; FY and period are still appended.",
            ),
        ),
        migrations.RunPython(ensure_standard_folders, noop),
    ]
