from django.urls import path

from . import views

urlpatterns = [
    path("groups/", views.group_list, name="accounts_group_list"),
    path("groups/new/", views.group_create, name="accounts_group_create"),
    path("groups/bulk-upload/", views.group_bulk_import, name="accounts_group_bulk_import"),
    path(
        "groups/primary-bulk-upload/",
        views.primary_group_bulk_import,
        name="accounts_primary_group_bulk_import",
    ),
    path(
        "groups/primary-bulk-upload/template/",
        views.primary_group_bulk_import_template,
        name="accounts_primary_group_bulk_import_template",
    ),
    path(
        "groups/bulk-upload/template/",
        views.group_bulk_import_template,
        name="accounts_group_bulk_import_template",
    ),
    path("groups/<int:pk>/", views.group_edit, name="accounts_group_edit"),
    path("groups/<int:pk>/delete/", views.group_delete, name="accounts_group_delete"),
    path(
        "ledgers/sync-clients/",
        views.sync_client_ledgers,
        name="accounts_sync_client_ledgers",
    ),
    path("ledgers/", views.account_list, name="accounts_account_list"),
    path("ledgers/new/", views.account_create, name="accounts_account_create"),
    path("ledgers/bulk-upload/", views.account_bulk_import, name="accounts_account_bulk_import"),
    path(
        "ledgers/bulk-upload/template/",
        views.account_bulk_import_template,
        name="accounts_account_bulk_import_template",
    ),
    path("ledgers/<int:pk>/", views.account_edit, name="accounts_account_edit"),
    path("ledgers/<int:pk>/delete/", views.account_delete, name="accounts_account_delete"),
    path("ledgers/<int:pk>/outstanding/", views.account_outstanding, name="accounts_account_outstanding"),
    path("vouchers/", views.voucher_list, name="accounts_voucher_list"),
    path("vouchers/new/", views.voucher_create, name="accounts_voucher_create"),
    path("vouchers/<int:pk>/", views.voucher_detail, name="accounts_voucher_detail"),
    path("vouchers/<int:pk>/edit/", views.voucher_edit, name="accounts_voucher_edit"),
    path("vouchers/<int:pk>/delete/", views.voucher_delete, name="accounts_voucher_delete"),
    path("vouchers/<int:pk>/invoice/", views.sales_invoice_print, name="accounts_sales_invoice_print"),
    path("unbilled/", views.unbilled_tasks, name="accounts_unbilled_tasks"),
    path("reports/trial-balance/", views.report_trial_balance, name="accounts_trial_balance"),
    path("reports/profit-loss/", views.report_profit_loss, name="accounts_profit_loss"),
    path("reports/balance-sheet/", views.report_balance_sheet, name="accounts_balance_sheet"),
    path("reports/ledger/", views.report_ledger, name="accounts_ledger"),
    path("reports/register/", views.report_register, name="accounts_register"),
    path("reports/bill-wise-outstanding/", views.report_billwise_outstanding, name="accounts_billwise_outstanding"),
]
