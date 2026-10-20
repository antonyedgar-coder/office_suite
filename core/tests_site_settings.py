from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import SiteSettings

User = get_user_model()


class SiteSettingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="pass12345",
        )
        self.client = Client()

    def test_branding_settings_page_requires_superuser(self):
        from django.core.exceptions import PermissionDenied
        from django.test import RequestFactory

        from core.views import site_settings_edit

        user = User.objects.create_user(email="staff@example.com", password="pass12345")
        request = RequestFactory().get("/settings/branding/")
        request.user = user
        with self.assertRaises(PermissionDenied):
            site_settings_edit(request)

    def test_save_company_name(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("site_settings_edit"),
            {"company_name": "Sharma & Associates"},
        )
        self.assertEqual(response.status_code, 302)
        settings = SiteSettings.load()
        self.assertEqual(settings.company_name, "Sharma & Associates")

    def test_save_gstin_and_address(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("site_settings_edit"),
            {
                "company_name": "Sharma & Associates",
                "gstin": "32aaaaa0000a1z5",
                "address": "1 MG Road, Trivandrum",
            },
        )
        self.assertEqual(response.status_code, 302)
        settings = SiteSettings.load()
        self.assertEqual(settings.gstin, "32AAAAA0000A1Z5")
        self.assertEqual(settings.address, "1 MG Road, Trivandrum")

    def test_branding_in_context(self):
        from django.test import RequestFactory

        from core.context_processors import site_branding

        SiteSettings.objects.update_or_create(
            pk=1,
            defaults={"company_name": "Demo Firm"},
        )
        data = site_branding(RequestFactory().get("/"))
        self.assertEqual(data["site_company_name"], "Demo Firm")

    def test_save_layout_colours(self):
        from django.test import RequestFactory

        from core.context_processors import site_branding

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("site_settings_edit"),
            {
                "company_name": "Sharma & Associates",
                "theme_primary": "#1e3a5f",
                "theme_sidebar": "#e8eef5",
            },
        )
        self.assertEqual(response.status_code, 302)
        settings = SiteSettings.load()
        self.assertEqual(settings.theme_primary, "#1e3a5f")
        self.assertEqual(settings.theme_sidebar, "#e8eef5")
        data = site_branding(RequestFactory().get("/"))
        self.assertEqual(data["theme_primary"], "#1e3a5f")
        self.assertEqual(data["theme_sidebar"], "#e8eef5")
        self.assertEqual(data["theme_chart_palette"][0], "#1e3a5f")


class SettingsNavPlacementTests(TestCase):
    def test_settings_sits_next_to_logout_in_topbar(self):
        from pathlib import Path

        from django.conf import settings

        base = (Path(settings.BASE_DIR) / "templates/base.html").read_text(encoding="utf-8")
        footer = (Path(settings.BASE_DIR) / "templates/includes/app_sidebar_footer.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("settings_hub", base)
        self.assertLess(base.find("settings_hub"), base.find("logout"))
        self.assertNotIn("settings_hub", footer)


class DashboardMisFyTests(TestCase):
    def test_dashboard_does_not_show_mis_or_client_type_charts(self):
        from pathlib import Path

        from django.conf import settings

        template = (Path(settings.BASE_DIR) / "templates/dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn("MIS this financial year", template)
        self.assertNotIn("dashboard-mis-fy", template)
        self.assertNotIn("clientTypeChart", template)
        self.assertNotIn("misFyChart", template)
        self.assertNotIn(">Tips<", template)
        self.assertNotIn("MIS • Fees", template)
        self.assertNotIn("MIS • Receipts", template)
        self.assertNotIn("MIS • Client Expenses", template)
        self.assertNotIn("Client Master → ledgers", template)
        self.assertIn("col-12", template)

    def test_document_check_queue_card_follows_verify_queue(self):
        from pathlib import Path

        from django.conf import settings

        cards = (Path(settings.BASE_DIR) / "templates/includes/dashboard_action_cards.html").read_text(
            encoding="utf-8"
        )
        verify_at = cards.find("Verify queue")
        doc_at = cards.find("Document check queue")
        self.assertGreater(verify_at, 0)
        self.assertGreater(doc_at, verify_at)
        self.assertIn("task_document_check_queue", cards)
