from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test.utils import modify_settings

from masters.models import Client, ClientGroup
from tasks.models import Task, TaskGroup, TaskMaster, TaskRecurrenceEnrollment
from tasks.task_data_wipe import (
    delete_task_configuration_only,
    delete_task_instances_only,
)

User = get_user_model()


@modify_settings(INSTALLED_APPS={"append": "tasks.apps.TasksConfig"})
class TaskDataWipeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin@ex.com", password="pass12345")
        grp = ClientGroup.objects.create(name="WIPE GROUP")
        self.client = Client.objects.create(
            client_name="WIPE CORP",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234F",
        )
        self.task_group = TaskGroup.objects.create(name="GST", sort_order=1)
        self.master = TaskMaster.objects.create(
            task_group=self.task_group,
            name="GST Notice",
            is_recurring=False,
        )
        self.task = Task.objects.create(
            client=self.client,
            task_master=self.master,
            period_key="FY2025-26-2026-04",
            period_type="one_time",
            due_date=date(2026, 4, 15),
            title="Notice",
            status=Task.STATUS_ASSIGNED,
            document_checker=self.user,
        )
        self.task.verifiers.set([self.user])

    def test_delete_instances_keeps_masters_and_groups(self):
        deleted = delete_task_instances_only()
        self.assertEqual(deleted["tasks"], 1)
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(TaskMaster.objects.count(), 1)
        self.assertEqual(TaskGroup.objects.count(), 1)

    def test_delete_configuration_requires_no_tasks(self):
        with self.assertRaises(ValidationError):
            delete_task_configuration_only()

    def test_delete_configuration_after_instances_removed(self):
        delete_task_instances_only()
        deleted = delete_task_configuration_only()
        self.assertEqual(deleted["task_masters"], 1)
        self.assertEqual(deleted["task_groups"], 1)
        self.assertEqual(TaskMaster.objects.count(), 0)
        self.assertEqual(TaskGroup.objects.count(), 0)

    def test_delete_instances_removes_enrollments(self):
        TaskRecurrenceEnrollment.objects.create(
            client=self.client,
            task_master=self.master,
            document_checker=self.user,
            started_at=date(2026, 4, 1),
        )
        delete_task_instances_only()
        self.assertEqual(TaskRecurrenceEnrollment.objects.count(), 0)
