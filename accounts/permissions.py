from .models import (
    VOUCHER_CONTRA,
    VOUCHER_CREDIT_NOTE,
    VOUCHER_DEBIT_NOTE,
    VOUCHER_JOURNAL,
    VOUCHER_PAYMENT,
    VOUCHER_PURCHASE,
    VOUCHER_RECEIPT,
    VOUCHER_SALES,
    VOUCHER_TABS,
)

PERM_ADD_PAYMENT = "accounts.add_payment_voucher"
PERM_CHANGE_PAYMENT = "accounts.change_payment_voucher"
PERM_DELETE_PAYMENT = "accounts.delete_payment_voucher"
PERM_PRINT_PAYMENT = "accounts.print_payment_voucher"
PERM_VIEW_VOUCHER = "accounts.view_voucher"
PERM_POST_VOUCHER = "accounts.post_voucher"
VOUCHER_LIST_PERMS = {
    VOUCHER_SALES: "accounts.list_sales_voucher",
    VOUCHER_PURCHASE: "accounts.list_purchase_voucher",
    VOUCHER_RECEIPT: "accounts.list_receipt_voucher",
    VOUCHER_PAYMENT: "accounts.list_payment_voucher",
    VOUCHER_CONTRA: "accounts.list_contra_voucher",
    VOUCHER_JOURNAL: "accounts.list_journal_voucher",
    VOUCHER_DEBIT_NOTE: "accounts.list_debit_note_voucher",
    VOUCHER_CREDIT_NOTE: "accounts.list_credit_note_voucher",
}

PAYMENT_VOUCHER_PERMS = (
    PERM_ADD_PAYMENT,
    PERM_CHANGE_PAYMENT,
    PERM_DELETE_PAYMENT,
    PERM_PRINT_PAYMENT,
)


def _has(user, perm: str) -> bool:
    return bool(user and user.is_authenticated and user.has_perm(perm))


def has_any_payment_voucher_perm(user) -> bool:
    return any(_has(user, perm) for perm in PAYMENT_VOUCHER_PERMS)


def can_view_voucher_type(user, vtype: str) -> bool:
    list_perm = VOUCHER_LIST_PERMS.get(vtype)
    if list_perm and _has(user, list_perm):
        return True
    if vtype == VOUCHER_PAYMENT and has_any_payment_voucher_perm(user):
        return True
    return False


def can_add_voucher(user, vtype: str) -> bool:
    if vtype == VOUCHER_PAYMENT:
        return _has(user, PERM_ADD_PAYMENT)
    return _has(user, PERM_POST_VOUCHER)


def can_change_voucher(user, vtype: str) -> bool:
    if vtype == VOUCHER_PAYMENT:
        return _has(user, PERM_CHANGE_PAYMENT)
    return _has(user, PERM_POST_VOUCHER)


def can_delete_voucher(user, vtype: str) -> bool:
    if vtype == VOUCHER_PAYMENT:
        return _has(user, PERM_DELETE_PAYMENT)
    return _has(user, PERM_POST_VOUCHER)


def can_print_voucher(user, vtype: str) -> bool:
    if vtype == VOUCHER_PAYMENT:
        return _has(user, PERM_PRINT_PAYMENT)
    return _has(user, PERM_VIEW_VOUCHER)


def visible_voucher_tabs(user):
    return [(key, label) for key, label in VOUCHER_TABS if can_view_voucher_type(user, key)]


def first_addable_voucher_type(user) -> str | None:
    for key, _label in VOUCHER_TABS:
        if can_add_voucher(user, key):
            return key
    return None


def voucher_action_flags(user, vtype: str) -> dict:
    return {
        "can_add": can_add_voucher(user, vtype),
        "can_change": can_change_voucher(user, vtype),
        "can_delete": can_delete_voucher(user, vtype),
        "can_print": can_print_voucher(user, vtype),
        "voucher_tabs": visible_voucher_tabs(user),
    }
