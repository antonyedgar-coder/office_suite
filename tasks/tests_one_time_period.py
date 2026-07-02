from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import modify_settings

from documents.models import DocumentFolderTemplate, DocumentTypeTemplate
from documents.periods import PERIOD_MONTH
from documents.services import render_generated_filename
from masters.models import Client, ClientGroup
from tasks.models import Task, TaskGroup, TaskMaster
from tasks.one_time_period import (
    allocate_one_time_period_key,
    backfill_one_time_period_keys_for_client,
    build_one_time_period_key,
    parse_one_time_period_key,
)

User = get_user_model()


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class OneTimeFilenameTests(TestCase):
    def setUp(self):
        self.folder = DocumentFolderTemplate.objects.create(
            name="GST",
            slug="gst-one-time-filename",
            sort_order=1,
        )
        self.doc_type = DocumentTypeTemplate.objects.create(
            folder=self.folder,
            name="GST Return filed",
            slug="gst-return-filed",
            allowed_extensions="pdf",
            period_kind=PERIOD_MONTH,
        )
        self.client = Client.objects.create(
            client_name="Acme Corp",
            client_type="Individual",
            branch="Trivandrum",
            client_group=ClientGroup.objects.create(name="FN GROUP"),
            approval_status=Client.APPROVED,
            pan="ABCDE1234F",
        )

    def test_one_time_task_uses_file_type_name_not_task_master(self):
        master = TaskMaster.objects.create(
            task_group=TaskGroup.objects.create(name="GST", sort_order=1),
            name="GST Return",
            is_recurring=False,
        )
        verifier = User.objects.create_user(email="v-fn@ex.com", password="pass12345")
        document_checker = User.objects.create_user(email="d-fn@ex.com", password="pass12345")
        task = Task.objects.create(
            client=self.client,
            task_master=master,
            period_type="one_time",
            period_key="FY2024-25-2025-03",
            due_date=date(2025, 3, 15),
            title="One-time",
            status=Task.STATUS_ASSIGNED,
            document_checker=document_checker,
        )
        task.verifiers.set([verifier])
        name = render_generated_filename(
            self.doc_type,
            client=self.client,
            period_key="FY2024-25-2025-03",
            period_label="March",
            extension="pdf",
            task=task,
        )
        self.assertIn("GST Return filed", name)
        self.assertIn("Acme Corp", name)
        self.assertNotIn("GST Return-", name)
        self.assertTrue(name.endswith(".pdf"))

    def test_one_time_period_key_monthly_file_type(self):
        name = render_generated_filename(
            self.doc_type,
            client=self.client,
            period_key="FY2024-25-2025-03",
            period_label="March",
            extension="pdf",
            task=None,
        )
        self.assertIn("Mar", name)
        self.assertIn("2024-25", name)


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class OneTimePeriodKeyTests(TestCase):
    def setUp(self):
        self.verifier = User.objects.create_user(email="v-ot@ex.com", password="pass12345")
        self.document_checker = User.objects.create_user(email="d-ot@ex.com", password="pass12345")
        grp = ClientGroup.objects.create(name="OT GROUP")
        self.client = Client.objects.create(
            client_name="ACME CORP",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234F",
        )
        tg = TaskGroup.objects.create(name="GST", sort_order=1)
        self.master = TaskMaster.objects.create(
            task_group=tg,
            name="GST Return",
            is_recurring=False,
        )

    def test_build_and_parse(self):
        due = date(2025, 3, 15)
        pk = build_one_time_period_key(due)
        self.assertEqual(pk, "FY2024-25-2025-03")
        parsed = parse_one_time_period_key(pk)
        assert parsed is not None
        self.assertEqual(parsed["month_abbr"], "Mar")
        self.assertEqual(parsed["sequence"], 1)

    def test_sequence_suffix(self):
        due = date(2025, 3, 20)
        self.assertEqual(build_one_time_period_key(due, sequence=2), "FY2024-25-2025-03-2")

    def _create_one_time_task(self, *, master, period_key, due):
        task = Task.objects.create(
            client=self.client,
            task_master=master,
            period_key=period_key,
            period_type="one_time",
            due_date=due,
            title="One-time",
            status=Task.STATUS_ASSIGNED,
            document_checker=self.document_checker,
        )
        task.verifiers.set([self.verifier])
        return task

    def test_allocate_increments_for_same_month(self):
        due = date(2025, 3, 10)
        first = allocate_one_time_period_key(self.client, self.master, due)
        self._create_one_time_task(master=self.master, period_key=first, due=due)
        second = allocate_one_time_period_key(self.client, self.master, due)
        self.assertEqual(first, "FY2024-25-2025-03")
        self.assertEqual(second, "FY2024-25-2025-03-2")

    def test_allocate_separate_sequence_per_task_master_same_month(self):
        due = date(2026, 4, 15)
        other_master = TaskMaster.objects.create(
            task_group=TaskGroup.objects.create(name="ROC", sort_order=2),
            name="GST Notice",
            is_recurring=False,
        )
        gst_first = allocate_one_time_period_key(self.client, self.master, due)
        self._create_one_time_task(master=self.master, period_key=gst_first, due=due)
        dsc_first = allocate_one_time_period_key(self.client, other_master, due)
        self.assertEqual(gst_first, "FY2025-26-2026-04")
        self.assertEqual(dsc_first, "FY2025-26-2026-04")
        gst_second = allocate_one_time_period_key(self.client, self.master, due)
        self.assertEqual(gst_second, "FY2025-26-2026-04-2")

    def test_allocate_counts_legacy_one_time_rows(self):
        due = date(2026, 4, 15)
        self._create_one_time_task(
            master=self.master,
            period_key="one-time",
            due=due,
        )
        second = allocate_one_time_period_key(self.client, self.master, due)
        self.assertEqual(second, "FY2025-26-2026-04-2")

    def test_backfill_renumbers_existing_tasks(self):
        due = date(2026, 4, 10)
        due2 = date(2026, 4, 20)
        self._create_one_time_task(master=self.master, period_key="one-time", due=due)
        self._create_one_time_task(master=self.master, period_key="one-time", due=due2)
        updated = backfill_one_time_period_keys_for_client(self.client, dry_run=False)
        self.assertEqual(updated, 2)
        keys = list(
            Task.objects.filter(client=self.client, period_type="one_time")
            .order_by("created_at")
            .values_list("period_key", flat=True)
        )
        self.assertEqual(keys, ["FY2025-26-2026-04", "FY2025-26-2026-04-2"])

    def test_backfill_separate_sequences_per_task_master(self):
        due = date(2026, 4, 10)
        notice_master = TaskMaster.objects.create(
            task_group=TaskGroup.objects.create(name="NOTICE", sort_order=4),
            name="GST Notice",
            is_recurring=False,
        )
        self._create_one_time_task(master=self.master, period_key="one-time", due=due)
        self._create_one_time_task(master=notice_master, period_key="one-time", due=due)
        backfill_one_time_period_keys_for_client(self.client, dry_run=False)
        keys_by_master = {
            t.task_master_id: t.period_key
            for t in Task.objects.filter(client=self.client, period_type="one_time")
        }
        self.assertEqual(keys_by_master[self.master.pk], "FY2025-26-2026-04")
        self.assertEqual(keys_by_master[notice_master.pk], "FY2025-26-2026-04")

    def test_allocate_restarts_for_each_client(self):
        due = date(2026, 4, 15)
        other_client = Client.objects.create(
            client_name="BETA CORP",
            client_type="Individual",
            branch="Trivandrum",
            client_group=ClientGroup.objects.create(name="OT GROUP B"),
            approval_status=Client.APPROVED,
            pan="BCDEF1234G",
        )
        first_a = allocate_one_time_period_key(self.client, self.master, due)
        self._create_one_time_task(master=self.master, period_key=first_a, due=due)
        first_b = allocate_one_time_period_key(other_client, self.master, due)
        self.assertEqual(first_a, "FY2025-26-2026-04")
        self.assertEqual(first_b, "FY2025-26-2026-04")
