from django.db import migrations, models

from documents.periods import PERIOD_INDIAN_FY, PERIOD_KIND_CHOICES, PERIOD_NONE


def migrate_period_kinds(apps, schema_editor):
    DocumentTypeTemplate = apps.get_model("documents", "DocumentTypeTemplate")
    ClientDocument = apps.get_model("documents", "ClientDocument")

    fy_slugs = {"financial-statement", "trial-balance"}
    for dt in DocumentTypeTemplate.objects.all():
        if getattr(dt, "requires_financial_year", False) or dt.slug in fy_slugs:
            dt.period_kind = PERIOD_INDIAN_FY
        else:
            dt.period_kind = PERIOD_NONE
        dt.save(update_fields=["period_kind"])

    for doc in ClientDocument.objects.all():
        fy = (doc.financial_year or "").strip()
        if fy:
            doc.period_key = f"FY{fy}"
            doc.period_label = f"FY {fy}"
        else:
            doc.period_key = "once"
            doc.period_label = "One-time"
        doc.save(update_fields=["period_key", "period_label"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0005_documentfoldertemplate_client_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="documenttypetemplate",
            name="period_kind",
            field=models.CharField(
                choices=PERIOD_KIND_CHOICES,
                default=PERIOD_NONE,
                help_text="Controls which period field appears on upload.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="clientdocument",
            name="period_key",
            field=models.CharField(db_index=True, default="once", max_length=32),
        ),
        migrations.AddField(
            model_name="clientdocument",
            name="period_label",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.RunPython(migrate_period_kinds, noop),
        migrations.RemoveField(
            model_name="documenttypetemplate",
            name="requires_financial_year",
        ),
        migrations.RemoveIndex(
            model_name="clientdocument",
            name="documents_cl_client__b2e8d4_idx",
        ),
        migrations.AddIndex(
            model_name="clientdocument",
            index=models.Index(
                fields=["client", "document_type", "period_key", "status"],
                name="documents_cl_client__period_idx",
            ),
        ),
    ]
