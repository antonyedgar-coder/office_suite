from django.db import migrations


def seed_templates(apps, schema_editor):
    DocumentFolderTemplate = apps.get_model("documents", "DocumentFolderTemplate")
    DocumentTypeTemplate = apps.get_model("documents", "DocumentTypeTemplate")

    financials, _ = DocumentFolderTemplate.objects.get_or_create(
        slug="financials",
        defaults={"name": "Financials", "sort_order": 10, "is_active": True},
    )
    kyc, _ = DocumentFolderTemplate.objects.get_or_create(
        slug="kyc",
        defaults={"name": "KYC", "sort_order": 20, "is_active": True},
    )

    types = [
        (
            financials,
            "financial-statement",
            "Financial Statement",
            "pdf",
            True,
            "{document_type}-{client_name}_{fy}",
            10,
        ),
        (
            financials,
            "trial-balance",
            "Trial Balance",
            "pdf,xlsx",
            True,
            "{document_type}-{client_name}_{fy}",
            20,
        ),
        (
            kyc,
            "pan-card",
            "PAN Card",
            "pdf",
            False,
            "{document_type}-{client_name}",
            10,
        ),
        (
            kyc,
            "aadhaar",
            "Aadhaar",
            "pdf",
            False,
            "{document_type}-{client_name}",
            20,
        ),
    ]
    for folder, slug, name, exts, req_fy, tmpl, order in types:
        DocumentTypeTemplate.objects.get_or_create(
            folder=folder,
            slug=slug,
            defaults={
                "name": name,
                "allowed_extensions": exts,
                "requires_financial_year": req_fy,
                "name_template": tmpl,
                "sort_order": order,
                "is_active": True,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_templates, noop),
    ]
