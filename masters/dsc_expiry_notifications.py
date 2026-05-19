"""DSC expiry in-app notifications (30 days before expiry, every 7 days)."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.branch_access import client_allowed_for_user
from core.models import Employee

from .models import ClientDSC

User = get_user_model()

DSC_EXPIRY_NOTIFY_DAYS_BEFORE = 30
DSC_EXPIRY_NOTIFY_INTERVAL_DAYS = 7


def get_latest_dsc_for_client(client_id: int) -> ClientDSC | None:
    return (
        ClientDSC.objects.filter(client_id=client_id)
        .select_related("client")
        .order_by("-expiry_date", "-pk")
        .first()
    )


def dsc_expiry_window_start(dsc: ClientDSC):
    return dsc.expiry_date - timedelta(days=DSC_EXPIRY_NOTIFY_DAYS_BEFORE)


def is_latest_dsc_for_client(dsc: ClientDSC) -> bool:
    latest = get_latest_dsc_for_client(dsc.client_id)
    return latest is not None and latest.pk == dsc.pk


def should_send_dsc_expiry_notification(dsc: ClientDSC, today=None) -> bool:
    """Whether this DSC (must be latest for client) should trigger reminders today."""
    today = today or timezone.localdate()
    if not dsc.expiry_notification:
        return False
    if not is_latest_dsc_for_client(dsc):
        return False
    if today > dsc.expiry_date:
        return False
    if today < dsc_expiry_window_start(dsc):
        return False
    if dsc.last_expiry_notification_sent_at:
        last_day = timezone.localdate(dsc.last_expiry_notification_sent_at)
        if (today - last_day).days < DSC_EXPIRY_NOTIFY_INTERVAL_DAYS:
            return False
    return True


def dsc_expiry_notification_recipients(dsc: ClientDSC) -> list[User]:
    """Users opted in + users with DSC view permission (branch-scoped)."""
    client = dsc.client
    user_ids: set[int] = set()

    for uid in Employee.objects.filter(
        receive_dsc_expiry_notifications=True,
        user_type=Employee.USER_TYPE_EMPLOYEE,
        user__is_active=True,
    ).values_list("user_id", flat=True):
        user_ids.add(uid)

    perm = Permission.objects.filter(
        content_type__app_label="masters",
        codename="view_clientdsc",
    ).first()
    if perm:
        via_direct = User.objects.filter(is_active=True, user_permissions=perm).values_list("pk", flat=True)
        via_group = User.objects.filter(is_active=True, groups__permissions=perm).values_list("pk", flat=True)
        user_ids.update(via_direct)
        user_ids.update(via_group)

    for u in User.objects.filter(is_active=True, is_superuser=True).values_list("pk", flat=True):
        user_ids.add(u)

    recipients = []
    for user in User.objects.filter(pk__in=user_ids, is_active=True):
        if client_allowed_for_user(user, client):
            recipients.append(user)
    return recipients


def build_dsc_expiry_message(dsc: ClientDSC, today=None) -> str:
    today = today or timezone.localdate()
    days_left = (dsc.expiry_date - today).days
    pan = (dsc.client.pan or "").strip().upper()
    name = dsc.client.client_name or dsc.client.client_id
    pan_part = f" (PAN {pan})" if pan else ""
    return (
        f"DSC for {name}{pan_part} expires on {dsc.expiry_date:%d-%m-%Y} "
        f"({days_left} day{'s' if days_left != 1 else ''} remaining)."
    )


def send_dsc_expiry_notifications(*, today=None, dry_run: bool = False) -> dict[str, int]:
    """
    Send reminders for each client's latest DSC when eligible.
    Returns counts: clients_checked, sent_batches, notifications_created.
    """
    from .models import DSCNotification

    today = today or timezone.localdate()
    client_ids = ClientDSC.objects.values_list("client_id", flat=True).distinct()
    sent_batches = 0
    notifications_created = 0
    clients_checked = 0

    for client_id in client_ids:
        dsc = get_latest_dsc_for_client(client_id)
        if not dsc:
            continue
        clients_checked += 1
        if not should_send_dsc_expiry_notification(dsc, today):
            continue

        message = build_dsc_expiry_message(dsc, today)
        link = reverse("dsc_edit", args=[dsc.pk])
        recipients = dsc_expiry_notification_recipients(dsc)
        if not recipients:
            continue

        if dry_run:
            sent_batches += 1
            notifications_created += len(recipients)
            continue

        for user in recipients:
            DSCNotification.objects.create(
                user=user,
                message=message,
                link=link,
                dsc=dsc,
            )
            notifications_created += 1

        dsc.last_expiry_notification_sent_at = timezone.now()
        dsc.save(update_fields=["last_expiry_notification_sent_at"])
        sent_batches += 1

    return {
        "clients_checked": clients_checked,
        "sent_batches": sent_batches,
        "notifications_created": notifications_created,
    }


def reset_dsc_expiry_notification_schedule(dsc: ClientDSC) -> None:
    """Clear send history so reminders can restart (e.g. expiry notification set to Yes)."""
    if dsc.last_expiry_notification_sent_at:
        dsc.last_expiry_notification_sent_at = None
        dsc.save(update_fields=["last_expiry_notification_sent_at"])
