from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.auth.models import Group
from django.test import TestCase, modify_settings

from core.models import Employee
from masters.models import Client, ClientActivityLog, ClientGroup
from tasks.checklist import (
    master_checklist_labels,
    save_master_checklist,
    set_task_checklist_item_status,
    toggle_task_checklist_item,
)
from tasks.forms import TaskCreateForm, TaskMasterForm
from tasks.models import (
    Task,
    TaskAssignment,
    TaskChecklistItem,
    TaskGroup,
    TaskMaster,
    TaskRecurrenceEnrollment,
)
from tasks.period_display import format_period_display
from tasks.period_keys import (
    build_period_key,
    current_fy_start,
    next_multi_year_span_after_last,
)
from tasks.one_time_period import allocate_one_time_period_key
from tasks.period_overlap import find_overlapping_task, period_interval, validate_no_overlapping_task
from tasks.user_labels import build_short_codes_for_users, short_code_for_user, user_person_name
from tasks.dashboard_counts import build_task_dashboard_context, task_due_bucket_counts
from tasks.recurrence import compute_create_due_dates
from tasks.models import TaskNotification
from tasks.services import (
    approve_task,
    approve_task_assignment,
    cancel_task,
    complete_task,
    create_task_from_master,
    task_team_is_editable,
    update_task_team,
    send_back_for_document_correction,
    submit_task,
    try_create_recurring_for_enrollment,
    verify_task,
)

User = get_user_model()


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="staff@example.com", password="pass12345")
        self.verifier = User.objects.create_user(email="verify@example.com", password="pass12345")
        self.document_checker = User.objects.create_user(email="docs@example.com", password="pass12345")
        grp = ClientGroup.objects.create(name="TEST GROUP")
        self.client = Client.objects.create(
            client_name="TEST CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234F",
        )
        tg = TaskGroup.objects.create(name="GST", sort_order=1)
        self.master = TaskMaster.objects.create(
            task_group=tg,
            name="GSTR-1",
            is_recurring=False,
        )

    def test_create_task_logs_client_activity(self):
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-08",
            due_date=date(2026, 8, 20),
            auto_created=True,
        )
        logs = ClientActivityLog.objects.filter(
            client=self.client,
            category=ClientActivityLog.CATEGORY_TASK,
            task=task,
        )
        self.assertGreaterEqual(logs.count(), 1)
        self.assertIn("GSTR-1", logs.first().activity)

    def test_update_task_team_changes_roles(self):
        new_assignee = User.objects.create_user(email="newuser@example.com", password="pass12345")
        new_verifier = User.objects.create_user(email="newverify@example.com", password="pass12345")
        new_doc = User.objects.create_user(email="newdocs@example.com", password="pass12345")
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-06",
            due_date=date(2026, 6, 15),
            auto_created=True,
        )
        update_task_team(
            task,
            assignee_users=[new_assignee],
            verifier=new_verifier,
            document_checker=new_doc,
            due_date=date(2026, 6, 20),
            priority=task.priority,
            actor=self.user,
        )
        task.refresh_from_db()
        self.assertTrue(task.verifiers.filter(pk=new_verifier.pk).exists())
        self.assertEqual(task.document_checker_id, new_doc.pk)
        self.assertEqual(task.due_date, date(2026, 6, 20))
        self.assertEqual(
            list(task.assignments.values_list("user_id", flat=True)),
            [new_assignee.pk],
        )

    def test_complete_task_cannot_edit_team(self):
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-07",
            due_date=date(2026, 7, 15),
            auto_created=True,
        )
        submit_task(task, self.user)
        verify_task(task, self.verifier)
        complete_task(task, self.document_checker)
        self.assertFalse(task_team_is_editable(task))

    def test_submit_verify_and_document_check_workflow(self):
        creator = User.objects.create_user(email="creator@example.com", password="pass12345")
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=creator,
            period_key="2026-05",
            due_date=date(2026, 5, 20),
            auto_created=True,
        )
        self.assertEqual(task.status, Task.STATUS_ASSIGNED)
        submit_task(task, self.user)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_SUBMITTED)
        self.assertIsNotNone(task.submitted_at)
        self.assertEqual(task.submitted_by_id, self.user.pk)
        verify_task(task, self.verifier)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_VERIFIED)
        self.assertIsNotNone(task.approved_at)
        self.assertEqual(task.approved_by_id, self.verifier.pk)
        complete_task(task, self.document_checker)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.completed_by_id, self.document_checker.pk)

    def test_new_client_cannot_submit_verifier_can_verify_directly(self):
        none_grp = ClientGroup.objects.create(name="NONE GRP")
        none_client = Client.objects.create(
            client_name="NONE CLIENT",
            client_type="New Client",
            branch="Trivandrum",
            client_group=none_grp,
            approval_status=Client.APPROVED,
        )
        tg = TaskGroup.objects.create(name="General", sort_order=2)
        master = TaskMaster.objects.create(task_group=tg, name="GSTR-3B", is_recurring=False)

        task = create_task_from_master(
            master=master,
            client=none_client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="none-1",
            due_date=date(2026, 6, 1),
            auto_created=True,
        )
        with self.assertRaises(ValidationError):
            submit_task(task, self.user)

        verify_task(task, self.verifier)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_VERIFIED)
        self.assertIsNone(task.submitted_at)
        self.assertEqual(task.approved_by_id, self.verifier.pk)
        complete_task(task, self.document_checker)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)

    def test_only_document_checker_can_complete(self):
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-09",
            due_date=date(2026, 9, 20),
            auto_created=True,
        )
        submit_task(task, self.user)
        verify_task(task, self.verifier)
        with self.assertRaises(ValidationError):
            complete_task(task, self.verifier)
        with self.assertRaises(ValidationError):
            complete_task(task, self.user)

    def test_document_checker_send_back_resubmit_skips_verifier(self):
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-10",
            due_date=date(2026, 10, 20),
            auto_created=True,
        )
        submit_task(task, self.user)
        verify_task(task, self.verifier)
        task.refresh_from_db()
        verifier_notify_before = TaskNotification.objects.filter(
            user=self.verifier, task=task
        ).count()

        send_back_for_document_correction(task, self.document_checker)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_DOCUMENT_REWORK)
        self.assertEqual(
            TaskNotification.objects.filter(user=self.verifier, task=task).count(),
            verifier_notify_before,
        )
        self.assertTrue(
            TaskNotification.objects.filter(user=self.user, task=task, kind=TaskNotification.KIND_REWORK).exists()
        )

        submit_task(task, self.user)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_VERIFIED)
        self.assertEqual(
            TaskNotification.objects.filter(user=self.verifier, task=task).count(),
            verifier_notify_before,
        )
        self.assertTrue(
            TaskNotification.objects.filter(
                user=self.document_checker,
                task=task,
                kind=TaskNotification.KIND_DOCUMENT_CHECK,
            ).exists()
        )

        complete_task(task, self.document_checker)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)

    def test_fees_snapshot_not_updated_on_master_change(self):
        task_old = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-04",
            due_date=date(2026, 4, 20),
            is_billable=True,
            fees_amount=Decimal("100.00"),
            auto_created=True,
        )
        task_new = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-06",
            due_date=date(2026, 6, 20),
            is_billable=True,
            fees_amount=Decimal("250.00"),
            auto_created=True,
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
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-07",
            due_date=date(2026, 7, 20),
            auto_created=True,
        )
        items = list(TaskChecklistItem.objects.filter(task=task).order_by("sort_order"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].label, "Collect documents")
        toggle_task_checklist_item(task=task, item_id=items[0].pk, user=self.user, done=True)
        items[0].refresh_from_db()
        self.assertTrue(items[0].is_done)
        with self.assertRaises(ValidationError):
            submit_task(task, self.user)
        set_task_checklist_item_status(
            task=task, item_id=items[1].pk, user=self.user, mode="na"
        )
        submit_task(task, self.user)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_SUBMITTED)
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
            document_checker=self.document_checker,
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
            document_checker=self.document_checker,
            created_by=self.user,
            period_key="2026-05",
            enrollment=enrollment,
            due_date=date(2026, 5, 20),
        )
        cancel_task(task, self.user)
        enrollment.refresh_from_db()
        self.assertFalse(enrollment.is_active)
        self.assertEqual(try_create_recurring_for_enrollment(enrollment, date(2026, 6, 1)), None)

    def test_manual_task_requires_assignee_approval(self):
        creator = User.objects.create_user(email="maker@example.com", password="pass12345")
        task = create_task_from_master(
            master=self.master,
            client=self.client,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.document_checker,
            created_by=creator,
            period_key="2026-08",
            due_date=date(2026, 8, 20),
        )
        self.assertEqual(task.status, Task.STATUS_PENDING_ASSIGNMENT)
        self.assertFalse(
            TaskNotification.objects.filter(
                user=self.user,
                kind=TaskNotification.KIND_ASSIGNED,
                task=task,
            ).exists()
        )
        self.assertTrue(
            TaskNotification.objects.filter(
                user=self.user,
                kind=TaskNotification.KIND_ASSIGNMENT_APPROVAL,
                task=task,
            ).exists()
        )
        self.assertFalse(
            TaskNotification.objects.filter(
                user=self.verifier,
                kind=TaskNotification.KIND_ASSIGNMENT_APPROVAL,
                task=task,
            ).exists()
        )
        approve_task_assignment(task, self.user)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_ASSIGNED)

    def test_creator_may_be_verifier_and_document_checker(self):
        creator = User.objects.create_user(email="creatorvc@example.com", password="pass12345")
        other = User.objects.create_user(email="assignee@example.com", password="pass12345")
        form = TaskCreateForm(
            data={
                "task_master": self.master.pk,
                "client": self.client.pk,
                "assignee_ids": str(other.pk),
                "verifier_ids": str(creator.pk),
                "document_checker": creator.pk,
                "due_date": "2026-09-15",
                "period_type": "monthly",
                "period_month": "9",
                "period_year": "2026",
            },
            user=creator,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_creator_cannot_be_assignee(self):
        creator = User.objects.create_user(email="creatora@example.com", password="pass12345")
        form = TaskCreateForm(
            data={
                "task_master": self.master.pk,
                "client": self.client.pk,
                "assignee_ids": str(creator.pk),
                "verifier_ids": str(self.verifier.pk),
                "document_checker": self.document_checker.pk,
                "due_date": "2026-09-15",
                "period_type": "monthly",
                "period_month": "9",
                "period_year": "2026",
            },
            user=creator,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("assignee_picker", form.errors)

    def test_recurring_create_form_sets_due_date_from_master(self):
        self.master.is_recurring = True
        self.master.frequency = TaskMaster.FREQ_MONTHLY
        self.master.recurrence_config = {"month_anchor": "same_month", "create_day": 1, "due_day": 15}
        self.master.save()
        other = User.objects.create_user(email="recassign@example.com", password="pass12345")
        form = TaskCreateForm(
            data={
                "task_master": self.master.pk,
                "client": self.client.pk,
                "assignee_ids": str(other.pk),
                "verifier_ids": str(self.verifier.pk),
                "document_checker": self.document_checker.pk,
                "period_type": "monthly",
                "period_month": "5",
                "period_year": "2026",
            },
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["due_date"], date(2026, 5, 15))

    def test_one_time_create_form_requires_due_date(self):
        other = User.objects.create_user(email="onceassign@example.com", password="pass12345")
        form = TaskCreateForm(
            data={
                "task_master": self.master.pk,
                "client": self.client.pk,
                "assignee_ids": str(other.pk),
                "verifier_ids": str(self.verifier.pk),
                "document_checker": self.document_checker.pk,
                "period_type": "monthly",
                "period_month": "5",
                "period_year": "2026",
            },
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("due_date", form.errors)


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
        self.assertEqual(labels[-1], "2030-31")

    def test_fy_choices_extend_when_current_fy_advances(self):
        from tasks.period_keys import task_fy_choices

        labels_before = [label for _, label in task_fy_choices(today=date(2027, 3, 31))]
        labels_after = [label for _, label in task_fy_choices(today=date(2027, 4, 1))]
        self.assertEqual(labels_before[-1], "2030-31")
        self.assertEqual(labels_after[-1], "2031-32")
        self.assertNotIn("2031-32", labels_before)

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

    def test_five_year_allows_partial_span(self):
        self.assertEqual(
            build_period_key("every_5_years", year_from=2026, year_to=2027),
            "2026-2027",
        )

    def test_five_year_rejects_more_than_five(self):
        with self.assertRaises(ValidationError):
            build_period_key("every_5_years", year_from=2020, year_to=2026)


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class PeriodOverlapTests(TestCase):
    def setUp(self):
        grp = ClientGroup.objects.create(name="OV GROUP")
        self.client = Client.objects.create(
            client_name="OV CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234A",
        )
        tg = TaskGroup.objects.create(name="OV TG")
        self.master = TaskMaster.objects.create(
            task_group=tg,
            name="Overlap task",
            is_recurring=True,
            frequency=TaskMaster.FREQ_MONTHLY,
            recurrence_config={"month_anchor": "same_month", "create_day": 1, "due_day": 20},
        )

    def _create(self, period_key: str, *, period_type: str = "monthly"):
        return Task.objects.create(
            client=self.client,
            task_master=self.master,
            title="T",
            status=Task.STATUS_ASSIGNED,
            due_date=date(2026, 5, 20),
            verifier=User.objects.create_user(email=f"v-{period_key}@ex.com", password="pass12345"),
            document_checker=User.objects.create_user(
                email=f"d-{period_key}@ex.com", password="pass12345"
            ),
            period_key=period_key,
            period_type=period_type,
        )

    def test_monthly_overlap_blocks_same_month(self):
        self._create("2026-05")
        with self.assertRaises(ValidationError):
            validate_no_overlapping_task(
                client=self.client,
                master=self.master,
                period_type="monthly",
                period_key="2026-05",
            )

    def test_one_time_allows_repeat_same_month(self):
        one_time_master = TaskMaster.objects.create(
            task_group=TaskGroup.objects.create(name="OT TG"),
            name="GST Notice",
            is_recurring=False,
        )
        due = date(2026, 5, 15)
        first_key = allocate_one_time_period_key(self.client, one_time_master, due)
        verifier = User.objects.create_user(email="v-ot1@ex.com", password="pass12345")
        document_checker = User.objects.create_user(email="d-ot1@ex.com", password="pass12345")
        task = Task.objects.create(
            client=self.client,
            task_master=one_time_master,
            title="First notice",
            status=Task.STATUS_ASSIGNED,
            due_date=due,
            document_checker=document_checker,
            period_key=first_key,
            period_type="one_time",
        )
        task.verifiers.set([verifier])
        second_key = allocate_one_time_period_key(self.client, one_time_master, due)
        self.assertNotEqual(first_key, second_key)
        validate_no_overlapping_task(
            client=self.client,
            master=one_time_master,
            period_type="one_time",
            period_key=second_key,
        )

    def test_three_year_blocks_until_next_period(self):
        master = TaskMaster.objects.create(
            task_group=TaskGroup.objects.create(name="3Y"),
            name="3y task",
            is_recurring=True,
            frequency=TaskMaster.FREQ_EVERY_3_YEARS,
            recurrence_config={
                "create_month": 4,
                "create_day": 1,
                "due_month": 7,
                "due_day": 15,
            },
        )
        Task.objects.create(
            client=self.client,
            task_master=master,
            title="3y",
            status=Task.STATUS_ASSIGNED,
            due_date=date(2026, 7, 5),
            verifier=User.objects.create_user(email="v3y@ex.com", password="pass12345"),
            document_checker=User.objects.create_user(email="d3y@ex.com", password="pass12345"),
            period_key="2026-2028",
            period_type="every_3_years",
        )
        with self.assertRaises(ValidationError):
            validate_no_overlapping_task(
                client=self.client,
                master=master,
                period_type="every_3_years",
                period_key="2027-2029",
            )
        validate_no_overlapping_task(
            client=self.client,
            master=master,
            period_type="every_3_years",
            period_key="2029-2031",
        )

    def test_next_multi_year_span_after_partial_five_year(self):
        master = TaskMaster.objects.create(
            task_group=TaskGroup.objects.create(name="5Y"),
            name="5y task",
            is_recurring=True,
            frequency=TaskMaster.FREQ_EVERY_5_YEARS,
            recurrence_config={
                "create_month": 4,
                "create_day": 1,
                "due_month": 7,
                "due_day": 15,
            },
        )
        Task.objects.create(
            client=self.client,
            task_master=master,
            title="5y",
            status=Task.STATUS_ASSIGNED,
            due_date=date(2026, 7, 5),
            verifier=User.objects.create_user(email="v5y@ex.com", password="pass12345"),
            document_checker=User.objects.create_user(email="d5y@ex.com", password="pass12345"),
            period_key="2026-2027",
            period_type="every_5_years",
        )
        nxt = next_multi_year_span_after_last(
            client=self.client,
            master=master,
            years=5,
            enrollment_started=date(2026, 7, 5),
            ref=date(2028, 4, 1),
        )
        self.assertEqual(nxt, "2028-2032")

    def test_three_year_interval_end_march_2029(self):
        iv = period_interval("every_3_years", "2026-2028")
        self.assertEqual(iv.end, date(2029, 3, 31))


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskListDisplayTests(TestCase):
    def test_period_columns_one_time(self):
        cols = format_period_display("FY2025-26-2026-04", period_type="one_time")
        self.assertEqual(cols.period, "April 2026")
        cols2 = format_period_display("FY2025-26-2026-04-2", period_type="one_time")
        self.assertEqual(cols2.period, "April 2026 (2)")

    def test_period_columns_monthly(self):
        cols = format_period_display("2026-05", period_type="monthly")
        self.assertEqual(cols.frequency, "Monthly")
        self.assertEqual(cols.period, "May 2026")

    def test_period_columns_quarterly(self):
        cols = format_period_display("2025-Q1", period_type="quarterly")
        self.assertEqual(cols.frequency, "Qtr")
        self.assertIn("Q1", cols.period)

    def test_period_columns_three_year_span(self):
        cols = format_period_display("2023-2025", period_type="every_3_years")
        self.assertEqual(cols.frequency, "3 years")
        self.assertIn("2023", cols.period)

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

    def test_annual_create_and_due_in_different_months(self):
        tg = TaskGroup.objects.create(name="ROC Annual")
        master = TaskMaster.objects.create(
            task_group=tg,
            name="Annual recurring filing",
            is_recurring=True,
            frequency=TaskMaster.FREQ_ANNUALLY,
            recurrence_config={
                "fy_anchor": "same_fy",
                "create_month": 4,
                "create_day": 1,
                "due_month": 7,
                "due_day": 15,
            },
        )
        create_d, due_d = compute_create_due_dates(master, "FY2025-26", date(2025, 4, 1))
        self.assertEqual(create_d, date(2025, 4, 1))
        self.assertEqual(due_d, date(2025, 7, 15))

    def test_annual_legacy_single_month_still_works(self):
        tg = TaskGroup.objects.create(name="Legacy Annual")
        master = TaskMaster.objects.create(
            task_group=tg,
            name="Legacy annual",
            is_recurring=True,
            frequency=TaskMaster.FREQ_ANNUALLY,
            recurrence_config={
                "fy_anchor": "same_fy",
                "month": 6,
                "create_day": 10,
                "due_day": 20,
            },
        )
        create_d, due_d = compute_create_due_dates(master, "FY2025-26", date(2025, 4, 1))
        self.assertEqual(create_d, date(2025, 6, 10))
        self.assertEqual(due_d, date(2025, 6, 20))


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
            pan="ABCDE1234B",
        )
        tg = TaskGroup.objects.create(name="ROC")
        self.master = TaskMaster.objects.create(
            task_group=tg,
            name="Annual filing",
            is_recurring=True,
            frequency=TaskMaster.FREQ_MONTHLY,
            recurrence_config={"month_anchor": "same_month", "create_day": 1, "due_day": 15},
        )
        self.document_checker = User.objects.create_user(email="docs@example.com", password="pass12345")
        self.enrollment = TaskRecurrenceEnrollment.objects.create(
            client=self.client,
            task_master=self.master,
            verifier=self.verifier,
            document_checker=self.document_checker,
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


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskDashboardDueBucketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="dash@example.com", password="pass12345")
        grp = ClientGroup.objects.create(name="DASH GROUP")
        self.client = Client.objects.create(
            client_name="DASH CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234C",
        )
        tg = TaskGroup.objects.create(name="Dash TG")
        self.master = TaskMaster.objects.create(task_group=tg, name="Dash task")

    def _task(self, due: date, *, status=Task.STATUS_ASSIGNED, period_key: str | None = None):
        return Task.objects.create(
            client=self.client,
            task_master=self.master,
            title="T",
            status=status,
            due_date=due,
            verifier=self.user,
            document_checker=self.user,
            period_key=period_key or f"one-time-{due.isoformat()}-{status}",
            created_by=self.user,
        )

    def test_due_buckets_mutually_exclusive(self):
        today = date(2026, 5, 17)
        self._task(today)
        self._task(today + timedelta(days=3))
        self._task(today + timedelta(days=8))
        self._task(today - timedelta(days=2))
        self._task(today - timedelta(days=10))
        self._task(today - timedelta(days=40))
        self._task(today, status=Task.STATUS_COMPLETE)

        c = task_due_bucket_counts(Task.objects.all(), today=today)
        self.assertEqual(c["due_today"], 1)
        self.assertEqual(c["due_next_7_days"], 1)
        self.assertEqual(c["overdue_up_to_7"], 1)
        self.assertEqual(c["overdue_up_to_30"], 1)
        self.assertEqual(c["overdue_over_30"], 1)

    def test_overdue_13_days_in_up_to_30_bucket(self):
        today = date(2026, 5, 18)
        due = date(2026, 5, 5)
        self._task(due)
        c = task_due_bucket_counts(Task.objects.all(), today=today)
        self.assertEqual(c["overdue_up_to_7"], 0)
        self.assertEqual(c["overdue_up_to_30"], 1)
        self.assertEqual(c["overdue_over_30"], 0)


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskDashboardContextTests(TestCase):
    def setUp(self):
        self.assignee = User.objects.create_user(email="worker@example.com", password="pass12345")
        self.verifier = User.objects.create_user(email="ver@example.com", password="pass12345")
        grp = ClientGroup.objects.create(name="CTX GROUP")
        self.client_row = Client.objects.create(
            client_name="CTX CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234D",
        )
        tg = TaskGroup.objects.create(name="CTX TG")
        self.master = TaskMaster.objects.create(task_group=tg, name="Ctx task")

    def test_dashboard_context_without_view_task_permission(self):
        Task.objects.create(
            client=self.client_row,
            task_master=self.master,
            title="T",
            status=Task.STATUS_ASSIGNED,
            due_date=date(2026, 6, 1),
            verifier=self.verifier,
            document_checker=self.verifier,
            period_key="ctx-1",
            created_by=self.verifier,
        )
        task = Task.objects.get(period_key="ctx-1")
        TaskAssignment.objects.create(task=task, user=self.assignee)

        ctx = build_task_dashboard_context(self.assignee)
        self.assertIsNotNone(ctx)
        self.assertFalse(ctx["task_dashboard_office_view"])
        self.assertEqual(ctx["task_counts"]["my_open"], 1)
        self.assertNotIn("total_open", ctx["task_counts"])
        self.assertTrue(ctx["task_due_buckets"])
        my_open_card = next(c for c in ctx["task_detail_cards"] if c.key == "my_open")
        self.assertIn("task_my_list", my_open_card.list_url)
        submitted_card = next(c for c in ctx["task_detail_cards"] if c.key == "my_submitted")
        self.assertIn("status=submitted", submitted_card.list_url)


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskMasterFormTests(TestCase):
    def test_create_without_currency_field_in_post(self):
        tg = TaskGroup.objects.create(name="Form TG", is_active=True)
        form = TaskMasterForm(
            data={
                "task_group": str(tg.pk),
                "name": "GSTR-3B",
                "description": "",
                "default_priority": TaskMaster.PRIORITY_NORMAL,
                "is_active": "on",
                "is_recurring": "",
                "frequency": "",
                "recurrence_config_json": "{}",
                "checklist_json": "[]",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        master = form.save()
        self.assertEqual(master.default_currency, TaskMaster.CURRENCY_INR)
        self.assertEqual(master.name, "GSTR-3B")


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class InactiveTaskMasterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="staff@example.com", password="pass12345")
        self.verifier = User.objects.create_user(email="verify@example.com", password="pass12345")
        self.document_checker = User.objects.create_user(email="docs@example.com", password="pass12345")
        grp = ClientGroup.objects.create(name="INACTIVE TG")
        self.client = Client.objects.create(
            client_name="INACTIVE CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234G",
        )
        tg = TaskGroup.objects.create(name="GST", sort_order=1)
        self.active_master = TaskMaster.objects.create(task_group=tg, name="Active master", is_active=True)
        self.inactive_master = TaskMaster.objects.create(
            task_group=tg, name="Inactive master", is_active=False
        )

    def test_selectable_for_new_tasks_excludes_inactive(self):
        ids = set(TaskMaster.selectable_for_new_tasks().values_list("pk", flat=True))
        self.assertIn(self.active_master.pk, ids)
        self.assertNotIn(self.inactive_master.pk, ids)

    def test_create_task_from_master_rejects_inactive(self):
        with self.assertRaises(ValidationError) as ctx:
            create_task_from_master(
                master=self.inactive_master,
                client=self.client,
                assignee_users=[self.user],
                verifier=self.verifier,
                document_checker=self.document_checker,
                created_by=self.user,
                period_key="2026-08",
                due_date=date(2026, 8, 20),
            )
        self.assertIn("inactive", str(ctx.exception).lower())

    def test_recurring_skips_inactive_master(self):
        from tasks.models import TaskEnrollmentAssignee

        self.inactive_master.is_recurring = True
        self.inactive_master.frequency = TaskMaster.FREQ_MONTHLY
        self.inactive_master.recurrence_config = {"day_of_month": 15}
        self.inactive_master.save()
        enrollment = TaskRecurrenceEnrollment.objects.create(
            client=self.client,
            task_master=self.inactive_master,
            verifier=self.verifier,
            document_checker=self.document_checker,
            started_at=date(2026, 1, 1),
            created_by=self.user,
            is_active=True,
        )
        TaskEnrollmentAssignee.objects.create(enrollment=enrollment, user=self.user)
        result = try_create_recurring_for_enrollment(enrollment, today=date(2026, 2, 15))
        self.assertIsNone(result)


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskCsvImportTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(email="creator@example.com", password="pass12345")
        self.assignee = User.objects.create_user(email="assign@example.com", password="pass12345")
        self.verifier = User.objects.create_user(email="verify@example.com", password="pass12345")
        self.document_checker = User.objects.create_user(email="docs@example.com", password="pass12345")
        grp = ClientGroup.objects.create(name="CSV GRP")
        self.client_row = Client.objects.create(
            client_name="CSV CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            client_id="CSV001",
            approval_status=Client.APPROVED,
            pan="ABCDE1234E",
        )
        tg = TaskGroup.objects.create(name="CSV TG")
        self.master = TaskMaster.objects.create(
            task_group=tg,
            name="CSV Master",
            is_recurring=True,
            frequency=TaskMaster.FREQ_MONTHLY,
            recurrence_config={
                "create_day": 1,
                "due_day": 18,
                "month_anchor": "same_month",
            },
        )
        self.one_time_master = TaskMaster.objects.create(
            task_group=tg,
            name="CSV One Time",
            is_recurring=False,
        )

    def test_parse_valid_row(self):
        from tasks.task_csv_import import parse_tasks_csv

        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            "CSV001,CSV TG|CSV Master,assign@example.com,verify@example.com,docs@example.com,monthly,"
            "5,2026,,,,,18-05-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].errors, [])
        self.assertEqual(rows[0].data["period_key"], "2026-05")

    def test_parse_invalid_row_shows_row_errors(self):
        from tasks.task_csv_import import parse_tasks_csv

        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            "BAD001,CSV TG|CSV Master,assign@example.com,verify@example.com,docs@example.com,monthly,"
            "5,2026,,,,,18-05-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].errors)
        self.assertIn("CLIENT_ID not found", rows[0].errors[0])
        self.assertEqual(rows[0].data.get("client_id_display"), "BAD001")
        self.assertEqual(rows[0].data.get("task_master_display"), "CSV TG|CSV Master")

    def test_parse_fy_range_format_2025_26(self):
        from tasks.task_csv_import import parse_tasks_csv

        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            "CSV001,CSV TG|CSV Master,assign@example.com,verify@example.com,docs@example.com,monthly,"
            "5,2025-26,,,,,05-06-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].data["period_key"], "2026-05")

    def test_parse_one_time_duplicate_rows_allowed(self):
        from tasks.task_csv_import import parse_tasks_csv

        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            "CSV001,CSV TG|CSV One Time,assign@example.com,verify@example.com,docs@example.com,one_time,"
            ",,,,,,11-05-2026,normal,NO,\n"
            "CSV001,CSV TG|CSV One Time,assign@example.com,verify@example.com,docs@example.com,one_time,"
            ",,,,,,11-05-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].errors, [])
        self.assertEqual(rows[1].errors, [])
        self.assertNotEqual(rows[0].data["period_key"], rows[1].data["period_key"])

    def test_parse_one_time_blank_period_type_for_non_recurring_master(self):
        from tasks.task_csv_import import parse_tasks_csv

        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            "CSV001,CSV TG|CSV One Time,assign@example.com,verify@example.com,docs@example.com,,"
            ",,,,,,11-04-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].errors, [])
        self.assertEqual(rows[0].data["period_type"], "one_time")
        self.assertTrue(rows[0].data["period_key"].startswith("FY"))

    def test_parse_quarter_number_in_period_quarter(self):
        from tasks.task_csv_import import parse_tasks_csv

        quarterly_master = TaskMaster.objects.create(
            task_group=self.master.task_group,
            name="CSV Quarterly",
            is_recurring=True,
            frequency=TaskMaster.FREQ_QUARTERLY,
            recurrence_config={
                "create_day": 1,
                "due_day": 15,
                "quarter_anchor": "first_month_same_qtr",
            },
        )
        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            f"CSV001,CSV TG|{quarterly_master.name},assign@example.com,verify@example.com,docs@example.com,quarterly,"
            ",2025-26,4,,,,,15-01-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(rows[0].errors, [])
        self.assertEqual(rows[0].data["period_key"], "2025-Q4")

    def test_parse_month_name_in_period_month(self):
        from tasks.task_csv_import import parse_tasks_csv

        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            "CSV001,CSV TG|CSV Master,assign@example.com,verify@example.com,docs@example.com,monthly,"
            "May,2025-26,,,,,18-05-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(rows[0].errors, [])
        self.assertEqual(rows[0].data["period_key"], "2026-05")

    def test_parse_one_time_numbering_is_per_client(self):
        from tasks.task_csv_import import parse_tasks_csv

        grp2 = ClientGroup.objects.create(name="CSV GRP 2")
        client_b = Client.objects.create(
            client_name="CSV CLIENT B",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp2,
            client_id="CSV002",
            approval_status=Client.APPROVED,
            pan="BCDEF1234G",
        )
        self.assertIsNotNone(client_b)
        csv_text = (
            "CLIENT_ID,TASK_MASTER,ASSIGNEE_EMAILS,VERIFIER_EMAIL,DOCUMENT_CHECKER_EMAIL,PERIOD_TYPE,"
            "PERIOD_MONTH,PERIOD_FY,PERIOD_QUARTER,PERIOD_HALF,PERIOD_YEAR_FROM,"
            "PERIOD_YEAR_TO,DUE_DATE,PRIORITY,IS_BILLABLE,FEES_AMOUNT\n"
            "CSV001,CSV TG|CSV One Time,assign@example.com,verify@example.com,docs@example.com,one_time,"
            ",,,,,,11-04-2026,normal,NO,\n"
            "CSV002,CSV TG|CSV One Time,assign@example.com,verify@example.com,docs@example.com,one_time,"
            ",,,,,,11-04-2026,normal,NO,\n"
        )
        rows, errs = parse_tasks_csv(csv_text.encode(), user=self.creator)
        self.assertEqual(errs, [])
        self.assertEqual(rows[0].errors, [])
        self.assertEqual(rows[1].errors, [])
        self.assertEqual(rows[0].data["period_key"], rows[1].data["period_key"])
