from django.db import migrations, models


def backfill_group_ids(apps, schema_editor):
    ClientGroup = apps.get_model("masters", "ClientGroup")
    GroupSequence = apps.get_model("masters", "GroupSequence")

    def first_letter(n: str) -> str:
        for ch in (n or "").upper():
            if "A" <= ch <= "Z":
                return ch
        return "X"

    for g in ClientGroup.objects.order_by("pk"):
        if getattr(g, "group_id", None):
            continue
        lt = first_letter(g.name)
        seq, _ = GroupSequence.objects.get_or_create(letter=lt, defaults={"last_value": 0})
        seq.last_value += 1
        seq.save(update_fields=["last_value"])
        gid = f"GR{lt}{seq.last_value:03d}"
        ClientGroup.objects.filter(pk=g.pk).update(group_id=gid)


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0013_client_group_master"),
    ]

    operations = [
        migrations.CreateModel(
            name="GroupSequence",
            fields=[
                ("letter", models.CharField(max_length=1, primary_key=True, serialize=False)),
                ("last_value", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Group ID sequence",
                "verbose_name_plural": "Group ID sequences",
            },
        ),
        migrations.AddField(
            model_name="clientgroup",
            name="group_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                max_length=12,
                null=True,
                verbose_name="Group ID",
            ),
        ),
        migrations.RunPython(backfill_group_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="clientgroup",
            name="group_id",
            field=models.CharField(
                db_index=True,
                editable=False,
                max_length=12,
                unique=True,
                verbose_name="Group ID",
            ),
        ),
    ]
