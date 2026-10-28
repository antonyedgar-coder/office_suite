from .models import VOUCHER_ACTIVITY_ACTIONS, VOUCHER_ACTIVITY_LABELS, VOUCHER_TABS

VOUCHER_PERM_ACTIONS = tuple(action for action, _label in VOUCHER_ACTIVITY_ACTIONS)


def voucher_perm(vtype: str, action: str) -> str:
    return f"accounts.{action}_{vtype}_voucher"


def _has(user, perm: str) -> bool:
    return bool(user and user.is_authenticated and user.has_perm(perm))


def can_view_voucher_type(user, vtype: str) -> bool:
    return any(_has(user, voucher_perm(vtype, action)) for action in VOUCHER_PERM_ACTIONS)


def can_add_voucher(user, vtype: str) -> bool:
    return _has(user, voucher_perm(vtype, "add"))


def can_change_voucher(user, vtype: str) -> bool:
    return _has(user, voucher_perm(vtype, "change"))


def can_delete_voucher(user, vtype: str) -> bool:
    return _has(user, voucher_perm(vtype, "delete"))


def can_print_voucher(user, vtype: str) -> bool:
    return _has(user, voucher_perm(vtype, "print"))


def can_open_voucher_menu(user) -> bool:
    return any(can_view_voucher_type(user, key) for key, _label in VOUCHER_TABS)


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


def voucher_activity_names():
    return {
        f"{action}_{key}_voucher": f"{label} | {action_label}"
        for key, label in VOUCHER_ACTIVITY_LABELS
        for action, action_label in VOUCHER_ACTIVITY_ACTIONS
    }
