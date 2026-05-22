from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client as DjangoTestClient, TestCase

from masters.client_type_service import allow_task_submit_without_pan, is_pan_mandatory_for_type
from masters.models import Client, ClientGroup, ClientType
from tasks.client_type_rules import may_submit_for_client_type
from tasks.models import Task, TaskGroup, TaskMaster
from tasks.services import create_task_from_master, submit_task

User = get_user_model()


class ClientTypeMasterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ct@example.com", password="pass12345")
        ClientType.objects.get_or_create(
            name="Individual",
            defaults={"pan_mandatory": True, "allow_task_submit_without_pan": True, "sort_order": 10},
        )
        ClientType.objects.get_or_create(
            name="New Client",
            defaults={"pan_mandatory": False, "allow_task_submit_without_pan": False, "sort_order": 130},
        )
        ClientType.objects.get_or_create(
            name="One Off Client",
            defaults={"pan_mandatory": False, "allow_task_submit_without_pan": True, "sort_order": 140},
        )

    def test_seed_pan_mandatory_flags(self):
        self.assertTrue(is_pan_mandatory_for_type("Individual"))
        self.assertFalse(is_pan_mandatory_for_type("New Client"))
        self.assertTrue(allow_task_submit_without_pan("One Off Client"))
        self.assertFalse(allow_task_submit_without_pan("New Client"))

    def test_client_type_list_requires_permission(self):
        perm = Permission.objects.get(codename="view_clienttype", content_type__app_label="masters")
        self.user.user_permissions.add(perm)
        http = DjangoTestClient()
        http.force_login(self.user)
        self.assertEqual(http.get("/masters/client-types/").status_code, 200)

    def test_pan_mandatory_on_client_clean(self):
        grp = ClientGroup.objects.create(name="TGRP")
        c = Client(
            client_name="NO PAN CO",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            pan="",
        )
        with self.assertRaises(ValidationError) as ctx:
            c.full_clean()
        self.assertIn("pan", ctx.exception.message_dict)


class ClientTypeTaskSubmitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="taskct@example.com", password="pass12345")
        self.verifier = User.objects.create_user(email="verct@example.com", password="pass12345")
        self.doc = User.objects.create_user(email="docct@example.com", password="pass12345")
        ClientType.objects.get_or_create(
            name="One Off Client",
            defaults={"pan_mandatory": False, "allow_task_submit_without_pan": True},
        )
        ClientType.objects.get_or_create(
            name="New Client",
            defaults={"pan_mandatory": False, "allow_task_submit_without_pan": False},
        )
        grp = ClientGroup.objects.create(name="OGRP")
        self.one_off = Client.objects.create(
            client_name="ONE OFF",
            client_type="One Off Client",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="",
        )
        tg = TaskGroup.objects.create(name="G", sort_order=1)
        self.master = TaskMaster.objects.create(task_group=tg, name="T1", is_recurring=False)

    def test_one_off_without_pan_may_submit(self):
        task = create_task_from_master(
            master=self.master,
            client=self.one_off,
            assignee_users=[self.user],
            verifier=self.verifier,
            document_checker=self.doc,
            created_by=self.user,
            period_key="p1",
            due_date=date(2026, 6, 1),
        )
        self.assertTrue(may_submit_for_client_type(task))
        submit_task(task, self.user)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_SUBMITTED)
