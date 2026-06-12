from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client as DjangoTestClient, TestCase

from core.models import Employee
from masters.models import Client, ClientGroup, ExpenseCategory
from mis.models import ExpenseDetail, FeesDetail, Receipt, TenderDetail

User = get_user_model()


class _MisTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="mis@example.com", password="pass12345")
        Employee.objects.create(user=self.user, full_name="MIS Staff", user_type=Employee.USER_TYPE_EMPLOYEE)
        grp = ClientGroup.objects.create(name="TEST GROUP")
        self.client_record = Client.objects.create(
            client_name="TEST CLIENT",
            client_type="Individual",
            pan="ABCDE1234F",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            created_by=self.user,
        )
        self.http = DjangoTestClient()
        self.http.force_login(self.user)

    def _grant(self, *codenames):
        perms = [
            Permission.objects.get(codename=c, content_type__app_label="mis")
            for c in codenames
        ]
        self.user.user_permissions.add(*perms)


class MisEditFlowTests(_MisTestBase):
    def test_fees_create_then_edit_get(self):
        self._grant("add_feesdetail", "change_feesdetail", "view_feesdetail")
        create_resp = self.http.post(
            "/mis/fees/new/",
            {
                "date": "2026-05-24",
                "client": str(self.client_record.pk),
                "fees_amount": "1000.00",
                "expenses_invoice_amount": "0.00",
                "gst_amount": "180.00",
                "remarks": "Test fees",
            },
        )
        self.assertEqual(create_resp.status_code, 302, create_resp.content)
        obj = FeesDetail.objects.get()
        edit_resp = self.http.get(f"/mis/fees/{obj.pk}/")
        self.assertEqual(edit_resp.status_code, 200, edit_resp.content)

    def test_receipt_create_then_edit_get(self):
        self._grant("add_receipt", "change_receipt", "view_receipt")
        create_resp = self.http.post(
            "/mis/receipts/new/",
            {
                "date": "2026-05-24",
                "client": str(self.client_record.pk),
                "fees_received": "500.00",
                "expenses_received": "0.00",
                "remarks": "",
            },
        )
        self.assertEqual(create_resp.status_code, 302, create_resp.content)
        obj = Receipt.objects.get()
        edit_resp = self.http.get(f"/mis/receipts/{obj.pk}/")
        self.assertEqual(edit_resp.status_code, 200, edit_resp.content)

    def test_expense_create_then_edit_get(self):
        self._grant("add_expensedetail", "change_expensedetail", "view_expensedetail")
        cat = ExpenseCategory.objects.create(name="General", is_active=True)
        create_resp = self.http.post(
            "/mis/expenses/new/",
            {
                "date": "2026-05-24",
                "client": str(self.client_record.pk),
                "category": str(cat.pk),
                "payment_mode": "CASH",
                "expenses_paid": "250.00",
                "remarks": "",
            },
        )
        self.assertEqual(create_resp.status_code, 302, create_resp.content)
        obj = ExpenseDetail.objects.get()
        edit_resp = self.http.get(f"/mis/expenses/{obj.pk}/")
        self.assertEqual(edit_resp.status_code, 200, edit_resp.content)

    def test_tender_create_then_edit_get(self):
        self._grant("add_tenderdetail", "change_tenderdetail", "view_tenderdetail")
        create_resp = self.http.post(
            "/mis/tender/new/",
            {
                "date": "2026-05-24",
                "client": str(self.client_record.pk),
                "tender_fees": "100.00",
                "tender_deposit": "50.00",
                "remarks": "",
            },
        )
        self.assertEqual(create_resp.status_code, 302, create_resp.content)
        obj = TenderDetail.objects.get()
        edit_resp = self.http.get(f"/mis/tender/{obj.pk}/")
        self.assertEqual(edit_resp.status_code, 200, edit_resp.content)

    def test_fees_edit_post(self):
        self._grant("add_feesdetail", "change_feesdetail", "view_feesdetail")
        obj = FeesDetail.objects.create(
            date=date(2026, 5, 24),
            client=self.client_record,
            fees_amount=Decimal("1000.00"),
            expenses_invoice_amount=Decimal("0.00"),
            gst_amount=Decimal("180.00"),
        )
        edit_resp = self.http.post(
            f"/mis/fees/{obj.pk}/",
            {
                "date": "2026-05-25",
                "client": str(self.client_record.pk),
                "fees_amount": "2000.00",
                "expenses_invoice_amount": "100.00",
                "gst_amount": "360.00",
                "remarks": "Updated",
            },
        )
        self.assertEqual(edit_resp.status_code, 302, edit_resp.content)
        obj.refresh_from_db()
        self.assertEqual(obj.date, date(2026, 5, 25))
        self.assertEqual(obj.fees_amount, Decimal("2000.00"))

    def test_fees_edit_get_renders_saved_date(self):
        self._grant("change_feesdetail", "view_feesdetail")
        obj = FeesDetail.objects.create(
            date=date(2026, 5, 24),
            client=self.client_record,
            fees_amount=Decimal("500.00"),
            expenses_invoice_amount=Decimal("0.00"),
            gst_amount=Decimal("0.00"),
        )
        edit_resp = self.http.get(f"/mis/fees/{obj.pk}/")
        self.assertEqual(edit_resp.status_code, 200, edit_resp.content)
        self.assertIn(b'value="2026-05-24"', edit_resp.content)
        self.assertIn(b"mis-client-picker-data", edit_resp.content)

    def test_expense_edit_get_with_inactive_category(self):
        self._grant("change_expensedetail", "view_expensedetail")
        inactive = ExpenseCategory.objects.create(name="Legacy", is_active=False)
        obj = ExpenseDetail.objects.create(
            date=date(2026, 5, 24),
            client=self.client_record,
            category=inactive,
            payment_mode=ExpenseDetail.PaymentMode.CASH,
            expenses_paid=Decimal("75.00"),
        )
        edit_resp = self.http.get(f"/mis/expenses/{obj.pk}/")
        self.assertEqual(edit_resp.status_code, 200, edit_resp.content)
        self.assertIn(b"Legacy", edit_resp.content)
