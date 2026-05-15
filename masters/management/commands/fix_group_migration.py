"""
Repair a stuck masters.0014 migration on PostgreSQL (orphan group_id indexes).

Usage on DigitalOcean Console:
  python manage.py fix_group_migration
  python manage.py migrate --noinput
"""

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Drop orphan ClientGroup group_id indexes/columns from a failed 0014 migration."

    def handle(self, *args, **options):
        vendor = connection.vendor
        self.stdout.write(f"Database engine: {vendor}")
        if vendor != "postgresql":
            self.stdout.write(
                self.style.WARNING(
                    "This command is for PostgreSQL (cloud). Local SQLite does not use the _like indexes."
                )
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename LIKE '%clientgroup%'
                """
            )
            tables = [r[0] for r in cursor.fetchall()]
            self.stdout.write(f"ClientGroup tables: {tables or '(none)'}")

            cursor.execute(
                """
                SELECT indexname, tablename FROM pg_indexes
                WHERE tablename IN ('masters_clientgroup', 'master_clientgroup')
                  AND indexname ILIKE '%group_id%'
                """
            )
            indexes = cursor.fetchall()
            self.stdout.write(f"Group ID indexes: {indexes or '(none)'}")
            for indexname, _tablename in indexes:
                cursor.execute(f'DROP INDEX IF EXISTS "{indexname}"')
                self.stdout.write(self.style.SUCCESS(f"Dropped index {indexname}"))

            for table in tables:
                cursor.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s AND column_name = 'group_id'
                    """,
                    [table],
                )
                if cursor.fetchone():
                    cursor.execute(f'ALTER TABLE "{table}" DROP COLUMN group_id CASCADE')
                    self.stdout.write(self.style.SUCCESS(f"Dropped group_id column on {table}"))

            for seq_table in ("masters_groupsequence", "master_groupsequence"):
                cursor.execute(f"DROP TABLE IF EXISTS {seq_table} CASCADE")
            self.stdout.write("Dropped GroupSequence tables if present.")

            cursor.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename IN ('masters_clientgroup', 'master_clientgroup')
                  AND indexname ILIKE '%group_id%'
                """
            )
            remaining = cursor.fetchall()
            if remaining:
                self.stdout.write(self.style.ERROR(f"Indexes still present: {remaining}"))
            else:
                self.stdout.write(self.style.SUCCESS("Cleanup complete. Now run: python manage.py migrate --noinput"))
