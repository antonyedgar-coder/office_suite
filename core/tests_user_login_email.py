from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client as DjangoTestClient, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ActivityLog, Employee
from core.user_login_email import apply_user_login_email_change
from masters.models import Client, ClientGroup
from tasks.models import Task, TaskAssignment, TaskGroup, TaskMaster
from tasks.services import create_task_from_master

User = get_user_model()


class UserLoginEmailChangeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="pass12345",
        )
        self.user = User.objects.create_user(
            email="worker@example.com",
            password="pass12345",
        )
        self.employee = Employee.objects.create(
            user=self.user,
            user_type=Employee.USER_TYPE_EMPLOYEE,
            full_name="Worker One",
            date_of_joining=timezone.localdate(),
            created_by=self.admin,
        )
        ActivityLog.objects.create(
            user=self.user,
            user_email=self.user.email,
            method="GET",
            path="/tasks/",
        )

    def test_apply_user_login_email_change_updates_login_and_activity_log(self):
        user_pk = self.user.pk
        changed = apply_user_login_email_change(
            self.user,
            "new.worker@example.com",
            employee=self.employee,
        )
        self.assertTrue(changed)
        self.user.save()

        self.user.refresh_from_db()
        self.assertEqual(self.user.pk, user_pk)
        self.assertEqual(self.user.email, "new.worker@example.com")
        self.assertEqual(self.user.username, "new.worker@example.com")
        self.assertEqual(
            ActivityLog.objects.filter(user=self.user).values_list("user_email", flat=True).distinct().get(),
            "new.worker@example.com",
        )

    def test_apply_user_login_email_change_noop_for_same_email(self):
        self.assertFalse(
            apply_user_login_email_change(
                self.user,
                self.user.email,
                employee=self.employee,
            )
        )

    def test_task_assignments_stay_linked_after_email_change(self):
        grp = ClientGroup.objects.create(name="TEST GROUP")
        client = Client.objects.create(
            client_name="TEST CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234F",
        )
        tg = TaskGroup.objects.create(name="GST", sort_order=1)
        master = TaskMaster.objects.create(task_group=tg, name="GSTR-1", is_recurring=False)
        verifier = User.objects.create_user(email="verify@example.com", password="pass12345")
        task = create_task_from_master(
            master=master,
            client=client,
            assignee_users=[self.user],
            verifier=verifier,
            document_checker=self.admin,
            created_by=self.admin,
            period_key="2026-08",
            due_date=date(2026, 8, 20),
            auto_created=True,
        )
        assignment_pk = TaskAssignment.objects.get(task=task, user=self.user).pk

        apply_user_login_email_change(
            self.user,
            "renamed.worker@example.com",
            employee=self.employee,
        )
        self.user.save()

        assignment = TaskAssignment.objects.get(pk=assignment_pk)
        self.assertEqual(assignment.user_id, self.user.pk)
        self.assertEqual(assignment.user.email, "renamed.worker@example.com")
        self.assertTrue(Task.objects.filter(pk=task.pk, assignments__user=self.user).exists())

    def test_client_user_email_change_updates_client_master(self):
        grp = ClientGroup.objects.create(name="CLIENT GROUP")
        client = Client.objects.create(
            client_name="Portal Client",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="XYZAB5678C",
            email="portal@example.com",
        )
        client_user = User.objects.create_user(email="portal@example.com", password="pass12345")
        client_employee = Employee.objects.create(
            user=client_user,
            user_type=Employee.USER_TYPE_CLIENT,
            linked_client=client,
            full_name=client.client_name,
            created_by=self.admin,
        )

        apply_user_login_email_change(
            client_user,
            "portal.new@example.com",
            employee=client_employee,
        )
        client_user.save()

        client.refresh_from_db()
        client_user.refresh_from_db()
        self.assertEqual(client.email, "portal.new@example.com")
        self.assertEqual(client_user.email, "portal.new@example.com")

    def test_employee_edit_view_changes_login_email(self):
        http = DjangoTestClient()
        http.force_login(self.admin)
        response = http.post(
            reverse("user_edit", args=[self.employee.pk]),
            {
                "official_email": "edited.worker@example.com",
                "full_name": self.employee.full_name,
                "contact_no": "",
                "address": "",
                "date_of_joining": self.employee.date_of_joining.isoformat(),
                "contact_person": "",
                "aadhar_no": "",
                "branch_access": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "edited.worker@example.com")
