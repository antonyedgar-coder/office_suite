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
        user = User.objects.create_user(email="staff@example.com", password="pass12345")
        self.client.force_login(user)
        response = self.client.get(reverse("site_settings_edit"))
        self.assertEqual(response.status_code, 403)

    def test_save_company_name(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("site_settings_edit"),
            {"company_name": "Sharma & Associates"},
        )
        self.assertEqual(response.status_code, 302)
        settings = SiteSettings.load()
        self.assertEqual(settings.company_name, "Sharma & Associates")

    def test_branding_in_context(self):
        SiteSettings.objects.update_or_create(
            pk=1,
            defaults={"company_name": "Demo Firm"},
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Demo Firm")
        self.assertContains(response, "CA Office Suite")
