from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("fees/", views.fees_list, name="mis_fees_list"),
    path("fees/new/", views.fees_create, name="mis_fees_create"),
    path("fees/<int:pk>/delete/", views.fees_delete, name="mis_fees_delete"),
    path("fees/<int:pk>/", views.fees_edit, name="mis_fees_edit"),
    path("tender/", views.tender_list, name="mis_tender_list"),
    path("tender/new/", views.tender_create, name="mis_tender_create"),
    path("tender/<int:pk>/delete/", views.tender_delete, name="mis_tender_delete"),
    path("tender/<int:pk>/", views.tender_edit, name="mis_tender_edit"),
    path("receipts/", views.receipt_list, name="mis_receipt_list"),
    path("receipts/new/", views.receipt_create, name="mis_receipt_create"),
    path("receipts/<int:pk>/delete/", views.receipt_delete, name="mis_receipt_delete"),
    path("receipts/<int:pk>/", views.receipt_edit, name="mis_receipt_edit"),
    path("expenses/", views.expense_list, name="mis_expense_list"),
    path("expenses/new/", views.expense_create, name="mis_expense_create"),
    path("expenses/<int:pk>/delete/", views.expense_delete, name="mis_expense_delete"),
    path("expenses/<int:pk>/", views.expense_edit, name="mis_expense_edit"),
    path("bulk-upload/", views.mis_bulk_import, name="mis_bulk_import"),
    path("bulk-upload/template/", views.mis_bulk_import_template, name="mis_bulk_import_template"),

    # Backward-compatible links (old per-page bulk upload URLs)
    path("fees/import/", RedirectView.as_view(pattern_name="mis_bulk_import", permanent=False)),
    path("receipts/import/", RedirectView.as_view(pattern_name="mis_bulk_import", permanent=False)),
    path("expenses/import/", RedirectView.as_view(pattern_name="mis_bulk_import", permanent=False)),
]

