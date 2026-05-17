from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, modify_settings

from core.models import Employee
from masters.models import Client, ClientGroup
from tasks.checklist import master_checklist_labels, save_master_checklist, toggle_task_checklist_item
from tasks.models import Task, TaskChecklistItem, TaskGroup, TaskMaster, TaskRecurrenceEnrollment
from tasks.period_display import format_period_key
from tasks.period_keys import build_period_key, current_fy_start
from tasks.user_labels import build_short_codes_for_users, short_code_for_user, user_person_name
from tasks.recurrence import compute_create_due_dates
from tasks.services import (
    approve_task,
    cancel_task,
    create_task_from_master,
    submit_task,
    try_create_recurring_for_enrollment,
)

User = get_user_model()


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="staff@example.com", password="pass12345")
        self.verifier = User.objects.create_user(email="verify@example.com", password="pass12345")
        grp = ClientGroup.objects.create(name="TEST GROUP")
        self.client = Client.objects.create(
            client_name="TEST CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
        )
        tg = TaskGroup.objects.create(name="GST", sort_order=1)
        self.master = TaskMaster.objects.create(
            task_group=tg,
            name="GSTR-1",
            is_recurring=False,
        )

    def test_submit_and_approve_workflow(self):
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            created_by=self.user,
            period_key="2026-05",
            due_date=date(2026, 5, 20),
        )
        self.assertEqual(task.status, Task.STATUS_ASSIGNED)
        submit_task(task, self.user)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_SUBMITTED)
        self.assertIsNotNone(task.submitted_at)
        self.assertEqual(task.submitted_by_id, self.user.pk)
        approve_task(task, self.verifier)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_APPROVED)
        self.assertIsNotNone(task.approved_at)
        self.assertEqual(task.approved_by_id, self.verifier.pk)

    def test_fees_snapshot_not_updated_on_master_change(self):
        self.master.default_is_billable = True
        self.master.default_fees_amount = Decimal("100.00")
        self.master.save()
        task_old = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            created_by=self.user,
            period_key="2026-04",
            due_date=date(2026, 4, 20),
            is_billable=True,
            fees_amount=Decimal("100.00"),
        )
        self.master.default_fees_amount = Decimal("250.00")
        self.master.save()
        task_new = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            created_by=self.user,
            period_key="2026-06",
            due_date=date(2026, 6, 20),
        )
        task_old.refresh_from_db()
        task_new.refresh_from_db()
        self.assertEqual(task_old.fees_amount, Decimal("100.00"))
        self.assertEqual(task_new.fees_amount, Decimal("250.00"))

    def test_checklist_copied_and_toggle(self):
        save_master_checklist(self.master, ["Collect documents", "File return"])
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            created_by=self.user,
            period_key="2026-07",
            due_date=date(2026, 7, 20),
        )
        items = list(TaskChecklistItem.objects.filter(task=task).order_by("sort_order"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].label, "Collect documents")
        toggle_task_checklist_item(task=task, item_id=items[0].pk, user=self.user, done=True)
        items[0].refresh_from_db()
        self.assertTrue(items[0].is_done)
        save_master_checklist(self.master, ["Only new template item"])
        self.assertEqual(master_checklist_labels(self.master), ["Only new template item"])
        self.assertEqual(TaskChecklistItem.objects.filter(task=task).count(), 2)

    def test_cancel_stops_recurring_enrollment(self):
        self.master.is_recurring = True
        self.master.frequency = TaskMaster.FREQ_MONTHLY
        self.master.recurrence_config = {"month_anchor": "same_month", "create_day": 1, "due_day": 15}
        self.master.save()
        enrollment = TaskRecurrenceEnrollment.objects.create(
            client=self.client,
            task_master=self.master,
            verifier=self.verifier,
            started_at=date(2026, 5, 1),
            created_by=self.user,
            is_active=True,
        )
        enrollment.assignees.add(self.user)
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            created_by=self.user,
            period_key="2026-05",
            enrollment=enrollment,
            due_date=date(2026, 5, 20),
        )
        cancel_task(task, self.user)
        enrollment.refresh_from_db()
        self.assertFalse(enrollment.is_active)
        self.assertEqual(try_create_recurring_for_enrollment(enrollment, date(2026, 6, 1)), None)


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class DatePresetTests(TestCase):
    def test_last_fy_april_to_march(self):
        from tasks.date_presets import PRESET_LAST_FY, resolve_date_preset

        d_from, d_to = resolve_date_preset(PRESET_LAST_FY, today=date(2026, 5, 10))
        self.assertEqual(d_from, date(2025, 4, 1))
        self.assertEqual(d_to, date(2026, 3, 31))

    def test_this_fy_to_today(self):
        from tasks.date_presets import PRESET_THIS_FY, resolve_date_preset

        d_from, d_to = resolve_date_preset(PRESET_THIS_FY, today=date(2026, 5, 10))
        self.assertEqual(d_from, date(2026, 4, 1))
        self.assertEqual(d_to, date(2026, 5, 10))


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class PeriodKeyTests(TestCase):
    def test_monthly_period_key_with_fy(self):
        self.assertEqual(build_period_key("monthly", month=5, fy_start=2026), "2026-05")
        self.assertEqual(build_period_key("monthly", month=1, fy_start=2026), "2027-01")

    def test_fy_choices_start_at_2024(self):
        from tasks.period_keys import task_fy_choices

        labels = [label for _, label in task_fy_choices(today=date(2026, 5, 1))]
        self.assertEqual(labels[0], "2024-25")
        self.assertIn("2026-27", labels)

    def test_quarterly_period_key(self):
        self.assertEqual(build_period_key("quarterly", quarter="Q1", fy_start=2025), "2025-Q1")

    def test_current_fy_from_april(self):
        self.assertEqual(current_fy_start(today=date(2026, 3, 31)), 2025)
        self.assertEqual(current_fy_start(today=date(2026, 4, 1)), 2026)

    def test_three_year_span(self):
        self.assertEqual(
            build_period_key("every_3_years", year_from=2023, year_to=2025),
            "2023-2025",
        )


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskListDisplayTests(TestCase):
    def test_period_columns_monthly(self):
        cols = format_period_key("2026-05")
        self.assertEqual(cols.month, "May 2026")

    def test_user_person_name_from_employee_profile(self):
        u = User.objects.create_user(email="staff@example.com", password="pass12345")
        Employee.objects.create(
            user=u,
            full_name="Antony Edgar",
            user_type=Employee.USER_TYPE_EMPLOYEE,
            date_of_joining=date(2020, 1, 1),
        )
        self.assertEqual(user_person_name(u), "Antony Edgar")

    def test_short_codes_unique(self):
        u1 = User.objects.create_user(email="a@example.com", password="pass12345")
        u2 = User.objects.create_user(email="b@example.com", password="pass12345")
        Employee.objects.create(
            user=u1,
            full_name="Antony Edgar",
            user_type=Employee.USER_TYPE_EMPLOYEE,
            date_of_joining=date(2020, 1, 1),
        )
        Employee.objects.create(
            user=u2,
            full_name="Antony Adams",
            user_type=Employee.USER_TYPE_EMPLOYEE,
            date_of_joining=date(2020, 1, 1),
        )
        codes = build_short_codes_for_users([u1, u2])
        self.assertNotEqual(codes[u1.pk], codes[u2.pk])
        self.assertEqual(len(codes[u1.pk]), 2)


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class RecurrenceDateTests(TestCase):
    def test_monthly_subsequent_month_due_in_next_calendar_month(self):
        tg = TaskGroup.objects.create(name="GST")
        master = TaskMaster.objects.create(
            task_group=tg,
            name="GSTR monthly",
            is_recurring=True,
            frequency=TaskMaster.FREQ_MONTHLY,
            recurrence_config={
                "month_anchor": "subsequent_month",
                "create_day": 5,
                "due_day": 20,
            },
        )
        create_d, due_d = compute_create_due_dates(master, "2026-05", date(2026, 1, 1))
        self.assertEqual(create_d, date(2026, 5, 5))
        self.assertEqual(due_d, date(2026, 6, 20))


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class RecurringCreateTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name="Admin")
        self.admin = User.objects.create_user(email="admin@example.com", password="pass12345", is_staff=True)
        self.admin.groups.add(Group.objects.get(name="Admin"))
        self.assignee = User.objects.create_user(email="worker@example.com", password="pass12345", is_active=False)
        self.verifier = User.objects.create_user(email="v@example.com", password="pass12345")
        grp = ClientGroup.objects.create(name="G1")
        self.client = Client.objects.create(
            client_name="C1",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
        )
        tg = TaskGroup.objects.create(name="ROC")
        self.master = TaskMaster.objects.create(
            task_group=tg,
            name="Annual filing",
            is_recurring=True,
            frequency=TaskMaster.FREQ_MONTHLY,
            recurrence_config={"month_anchor": "same_month", "create_day": 1, "due_day": 15},
        )
        self.enrollment = TaskRecurrenceEnrollment.objects.create(
            client=self.client,
            task_master=self.master,
            verifier=self.verifier,
            started_at=date(2026, 5, 1),
            created_by=self.admin,
        )
        self.enrollment.assignees.add(self.assignee)

    def test_inactive_assignee_skips_create(self):
        from tasks.models import TaskNotification

        today = date(2026, 5, 1)
        result = try_create_recurring_for_enrollment(self.enrollment, today)
        self.assertIsNone(result)
        self.assertFalse(Task.objects.filter(client=self.client, task_master=self.master).exists())
        self.assertTrue(TaskNotification.objects.filter(kind=TaskNotification.KIND_RECURRING_FAIL).exists())
