"""DSC expiry in-app notifications (daily job, users with DSC view permission)."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from core.branch_access import client_allowed_for_user

from .models import ClientDSC

User = get_user_model()


def dsc_expiry_days_before() -> int:
    return int(getattr(settings, "DSC_EXPIRY_NOTIFY_DAYS_BEFORE", 30))


def dsc_expiry_users_with_view_permission() -> list[User]:
    """Active users who can view DSC (direct permission, group, or superuser)."""
    perm = Permission.objects.filter(
        content_type__app_label="masters",
        codename="view_clientdsc",
    ).first()
    user_ids: set[int] = set()
    if perm:
        user_ids.update(
            User.objects.filter(is_active=True, user_permissions=perm).values_list("pk", flat=True)
        )
        user_ids.update(
            User.objects.filter(is_active=True, groups__permissions=perm).values_list("pk", flat=True)
        )
    user_ids.update(User.objects.filter(is_active=True, is_superuser=True).values_list("pk", flat=True))
    return list(User.objects.filter(pk__in=user_ids, is_active=True).order_by("email"))


def user_receives_dsc_expiry_alerts(user) -> bool:
    if not user or not getattr(user, "is_active", False):
        return False
    return user.is_superuser or user.has_perm("masters.view_clientdsc")


def get_latest_dsc_for_client(client_id: int) -> ClientDSC | None:
    return (
        ClientDSC.objects.filter(client_id=client_id)
        .select_related("client")
        .order_by("-expiry_date", "-pk")
        .first()
    )


def dsc_expiry_window_start(dsc: ClientDSC):
    return dsc.expiry_date - timedelta(days=dsc_expiry_days_before())


def is_latest_dsc_for_client(dsc: ClientDSC) -> bool:
    latest = get_latest_dsc_for_client(dsc.client_id)
    return latest is not None and latest.pk == dsc.pk


def should_send_dsc_expiry_notification(dsc: ClientDSC, today=None) -> bool:
    """
    Whether this DSC (latest for client) should get reminders on ``today``.
    When the daily job runs, each eligible DSC is notified at most once per calendar day.
    """
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
        if last_day >= today:
            return False
    return True


def dsc_expiry_notification_recipients(dsc: ClientDSC) -> list[User]:
    """Users with DSC view access whose branch includes this client."""
    client = dsc.client
    recipients = []
    for user in dsc_expiry_users_with_view_permission():
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
    Create in-app DSC expiry alerts for eligible clients (latest DSC per client).
    Intended to run once per day via server cron at DSC_EXPIRY_NOTIFY_RUN_TIME.
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
