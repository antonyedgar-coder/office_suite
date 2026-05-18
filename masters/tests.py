from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client as DjangoTestClient, TestCase

from core.models import Employee
from masters.client_activity import log_client_activity
from masters.models import Client, ClientActivityLog, ClientGroup

User = get_user_model()


class ClientActivityLogTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="staff@example.com", password="pass12345")
        Employee.objects.create(user=self.user, full_name="Antony Edgar", user_type=Employee.USER_TYPE_EMPLOYEE)
        grp = ClientGroup.objects.create(name="TEST GROUP")
        self.client_record = Client.objects.create(
            client_name="TEST CLIENT",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            created_by=self.user,
        )
        self.http = DjangoTestClient()

    def test_log_client_activity_creates_row(self):
        row = log_client_activity(
            client=self.client_record,
            user=self.user,
            category=ClientActivityLog.CATEGORY_CLIENT,
            activity="Client master updated.",
        )
        self.assertIsNotNone(row)
        self.assertEqual(ClientActivityLog.objects.filter(client=self.client_record).count(), 1)
        stored = ClientActivityLog.objects.get(pk=row.pk)
        self.assertEqual(stored.activity, "Client master updated.")
        self.assertEqual(stored.get_category_display(), "Client Master")

    def test_client_edit_includes_activity_context(self):
        perm = Permission.objects.get(codename="view_client", content_type__app_label="masters")
        perm_change = Permission.objects.get(codename="change_client", content_type__app_label="masters")
        self.user.user_permissions.add(perm, perm_change)
        log_client_activity(
            client=self.client_record,
            user=self.user,
            category=ClientActivityLog.CATEGORY_CLIENT,
            activity="Client master updated.",
        )
        self.http.force_login(self.user)
        resp = self.http.get(f"/masters/clients/{self.client_record.client_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("activity_rows", resp.context)
        self.assertEqual(len(resp.context["activity_rows"]), 1)
