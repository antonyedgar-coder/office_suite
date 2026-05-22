from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from documents.task_bridge import document_period_from_task, task_allows_document_changes
from tasks.models import Task


class DocumentPeriodFromTaskTests(SimpleTestCase):
    def _task(self, **kwargs):
        return Task(period_key=kwargs.get("period_key", ""), period_type=kwargs.get("period_type", ""))

    def test_monthly_period_key(self):
        task = self._task(period_key="2025-04", period_type="monthly")
        key, label = document_period_from_task(task)
        self.assertTrue(key.startswith("FY"))
        self.assertIn("2025-04", key)
        self.assertEqual(label, "April")

    def test_quarterly(self):
        task = self._task(period_key="2025-Q2", period_type="quarterly")
        key, label = document_period_from_task(task)
        self.assertIn("Q2", key)
        self.assertEqual(label, "Q2")

    def test_multi_year_span(self):
        task = self._task(period_key="2023-2025", period_type="every_3_years")
        key, label = document_period_from_task(task)
        self.assertTrue(key.startswith("FY"))
        self.assertIn("2023", label)

    def test_one_time(self):
        task = self._task(period_key="one-time", period_type="one_time")
        self.assertEqual(document_period_from_task(task), ("once", "—"))


class TaskDocumentLockTests(SimpleTestCase):
    def test_complete_task_locks_documents(self):
        task = Task(status=Task.STATUS_COMPLETE)
        self.assertFalse(task_allows_document_changes(task))

    def test_document_rework_allows_changes(self):
        task = Task(status=Task.STATUS_DOCUMENT_REWORK)
        self.assertTrue(task_allows_document_changes(task))
