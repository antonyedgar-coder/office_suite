from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client as DjangoTestClient, TestCase

from core.models import Employee
from masters.client_activity import (
    CLIENT_ACTIVITY_DATE_PRESET_CHOICES,
    CLIENT_ACTIVITY_DEFAULT_DATE_PRESET,
    build_client_activity_list_rows,
    log_client_activity,
    parse_client_activity_log_filters,
    remark_text_for_log,
    task_type_label_for_log,
)
from masters.forms import DirectorMappingRowForm
from masters.models import Client, ClientActivityLog, ClientGroup
from tasks.date_presets import PRESET_ALL_TIME

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

    def test_client_activity_log_list_filters(self):
        perm = Permission.objects.get(codename="view_client", content_type__app_label="masters")
        self.user.user_permissions.add(perm)
        log_client_activity(
            client=self.client_record,
            user=self.user,
            category=ClientActivityLog.CATEGORY_CLIENT,
            activity="Client master created.",
        )
        self.http.force_login(self.user)
        resp = self.http.get(
            "/masters/clients/activity-log/",
            {
                "date_preset": "this_month",
                "client_q": self.client_record.client_name[:4],
                "category": ClientActivityLog.CATEGORY_CLIENT,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["activity_rows"]), 1)
        resp2 = self.http.get("/masters/clients/activity-log/", {"category": ClientActivityLog.CATEGORY_TASK})
        self.assertEqual(len(resp2.context["activity_rows"]), 0)

    def test_log_client_activity_stores_remarks_in_metadata(self):
        row = log_client_activity(
            client=self.client_record,
            user=self.user,
            category=ClientActivityLog.CATEGORY_CLIENT,
            activity="Client master updated.",
            remarks="PAN corrected",
        )
        self.assertEqual(row.metadata.get("remark"), "PAN corrected")
        self.assertEqual(remark_text_for_log(row), "PAN corrected")
        rows = build_client_activity_list_rows([row], can_link_tasks=False)
        self.assertEqual(rows[0]["remarks"], "PAN corrected")

    def test_activity_log_date_filter_defaults_to_all_time(self):
        self.assertEqual(CLIENT_ACTIVITY_DEFAULT_DATE_PRESET, PRESET_ALL_TIME)
        self.assertEqual(CLIENT_ACTIVITY_DATE_PRESET_CHOICES[0][0], PRESET_ALL_TIME)
        self.assertEqual(parse_client_activity_log_filters({}).date_preset, PRESET_ALL_TIME)

        perm = Permission.objects.get(codename="view_client", content_type__app_label="masters")
        self.user.user_permissions.add(perm)
        self.http.force_login(self.user)
        resp = self.http.get("/masters/clients/activity-log/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["filters"].date_preset, PRESET_ALL_TIME)
        content = resp.content.decode()
        self.assertIn('value="all_time"', content)
        pos_all = content.find("All time")
        pos_month = content.find("This month")
        self.assertNotEqual(pos_all, -1)
        self.assertNotEqual(pos_month, -1)
        self.assertLess(pos_all, pos_month)

    def test_parse_client_activity_log_filters_task_master_id(self):
        filters = parse_client_activity_log_filters({"task_master_id": "42"})
        self.assertEqual(filters.task_master_id, "42")

    def test_task_type_label_for_log(self):
        client_log = Mock(
            category=ClientActivityLog.CATEGORY_CLIENT,
            task_id=None,
            task=None,
        )
        self.assertEqual(task_type_label_for_log(client_log), "")

        task_log = Mock(
            category=ClientActivityLog.CATEGORY_TASK,
            task_id=1,
            task=Mock(task_master=Mock(name="  GSTR-3B  ")),
        )
        self.assertEqual(task_type_label_for_log(task_log), "GSTR-3B")

    def test_director_mapping_row_form_empty_row_checks_include_remarks(self):
        blank = DirectorMappingRowForm(data={})
        self.assertTrue(blank.is_valid())

        with_remarks = DirectorMappingRowForm(data={"remarks": "Appointment pending docs"})
        self.assertTrue(with_remarks.is_valid())
        self.assertEqual(with_remarks.cleaned_data.get("remarks"), "Appointment pending docs")
