from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import modify_settings

from documents.periods import build_one_time_task_filename
from masters.models import Client, ClientGroup
from tasks.models import Task, TaskGroup, TaskMaster
from tasks.one_time_period import (
    allocate_one_time_period_key,
    build_one_time_period_key,
    parse_one_time_period_key,
)


def _sanitize(value: str) -> str:
    return (value or "").strip().replace(" ", "_")


User = get_user_model()


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

    def test_allocate_increments_for_same_month(self):
        due = date(2025, 3, 10)
        first = allocate_one_time_period_key(self.client, self.master, due)
        Task.objects.create(
            client=self.client,
            task_master=self.master,
            period_key=first,
            period_type="one_time",
            due_date=due,
            title="First",
            status=Task.STATUS_ASSIGNED,
            verifier=self.verifier,
            document_checker=self.document_checker,
        )
        second = allocate_one_time_period_key(self.client, self.master, due)
        self.assertEqual(first, "FY2024-25-2025-03")
        self.assertEqual(second, "FY2024-25-2025-03-2")


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class OneTimeFilenameTests(TestCase):
    def test_filename_format(self):
        name = build_one_time_task_filename(
            task_master_name="GST Return",
            client_name="Acme Corp",
            period_key="FY2024-25-2025-03",
            extension="pdf",
            sanitize=_sanitize,
        )
        self.assertEqual(name, "GST_Return-Acme_Corp_FY2024-25_Mar.pdf")

    def test_filename_with_sequence(self):
        name = build_one_time_task_filename(
            task_master_name="GST Return",
            client_name="Acme Corp",
            period_key="FY2024-25-2025-03-2",
            extension="pdf",
            sanitize=_sanitize,
        )
        self.assertEqual(name, "GST_Return-Acme_Corp_FY2024-25_Mar_2.pdf")
