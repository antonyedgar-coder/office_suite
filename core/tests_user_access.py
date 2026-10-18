from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.employee_forms import EmployeeCreateForm, EmployeeEditForm
from core.group_forms import GroupAccessForm
from core.models import Employee
from core.permission_utils import manageable_permissions

User = get_user_model()


class DualListPermissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="access-admin@example.com",
            password="pass12345",
        )
        self.perm = manageable_permissions().first()

    def test_user_and_group_widgets_use_dual_list(self):
        self.assertIsNotNone(self.perm)
        create = EmployeeCreateForm()
        self.assertIn("js-dual-list", create.fields["user_permissions"].widget.attrs["class"])
        self.assertEqual(
            create.fields["user_permissions"].widget.attrs["data-available-label"],
            "Available activities",
        )
        edit = EmployeeEditForm()
        self.assertIn("js-dual-list", edit.fields["user_permissions"].widget.attrs["class"])
        group = GroupAccessForm()
        self.assertIn("js-dual-list", group.fields["assigned_permissions"].widget.attrs["class"])

    def test_group_form_saves_moved_permissions(self):
        form = GroupAccessForm(
            data={"name": "Dual list group", "assigned_permissions": [self.perm.pk]}
        )
        self.assertTrue(form.is_valid(), form.errors)
        group = form.save()
        self.assertTrue(group.permissions.filter(pk=self.perm.pk).exists())

    def test_user_create_saves_direct_permissions(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user_create"),
            {
                "user_type": Employee.USER_TYPE_EMPLOYEE,
                "official_email": "dual-list-staff@example.com",
                "full_name": "Dual List Staff",
                "date_of_joining": "2026-04-01",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "is_active": "on",
                "user_permissions": [str(self.perm.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="dual-list-staff@example.com")
        self.assertTrue(user.user_permissions.filter(pk=self.perm.pk).exists())

    @patch("core.permission_utils.accounts_module_enabled", return_value=True)
    def test_payment_voucher_activities_are_listed(self, _enabled):
        expected = {
            "add_payment_voucher": "Payment voucher | Add",
            "change_payment_voucher": "Payment voucher | Change",
            "delete_payment_voucher": "Payment voucher | Delete",
            "print_payment_voucher": "Payment voucher | Print",
        }
        found = {
            perm.codename: perm.name
            for perm in manageable_permissions().filter(
                content_type__app_label="accounts",
                content_type__model="voucher",
                codename__in=expected,
            )
        }
        self.assertEqual(found, expected)
        form = EmployeeCreateForm()
        form_names = {perm.name for perm in form.fields["user_permissions"].queryset}
        self.assertTrue(set(expected.values()) <= form_names)
        group = GroupAccessForm()
        group_names = {perm.name for perm in group.fields["assigned_permissions"].queryset}
        self.assertTrue(set(expected.values()) <= group_names)
