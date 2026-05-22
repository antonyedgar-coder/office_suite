"""Master request workflow — assignees, notifications, link-on-save."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode

from core.user_display import user_display_name

from .models import MasterRequest, MasterRequestNotification

User = get_user_model()

# Request type → Django permission (app_label, codename)
REQUEST_TYPE_PERMISSIONS: dict[str, tuple[str, str]] = {
    MasterRequest.TYPE_CLIENT_GROUP: ("masters", "add_clientgroup"),
    MasterRequest.TYPE_TASK_MASTER: ("tasks", "add_taskmaster"),
    MasterRequest.TYPE_TASK_GROUP: ("tasks", "add_taskgroup"),
    MasterRequest.TYPE_NEW_TASK: ("tasks", "add_task"),
    MasterRequest.TYPE_PORTAL_NAME: ("masters", "add_portalname"),
    MasterRequest.TYPE_CLIENT_TYPE: ("masters", "add_clienttype"),
    MasterRequest.TYPE_NEW_CLIENT: ("masters", "add_client"),
}

REQUEST_TYPE_CREATE_URL: dict[str, str] = {
    MasterRequest.TYPE_CLIENT_GROUP: "client_group_create",
    MasterRequest.TYPE_TASK_MASTER: "task_master_create",
    MasterRequest.TYPE_TASK_GROUP: "task_group_create",
    MasterRequest.TYPE_NEW_TASK: "task_create",
    MasterRequest.TYPE_PORTAL_NAME: "portal_name_create",
    MasterRequest.TYPE_CLIENT_TYPE: "client_type_create",
    MasterRequest.TYPE_NEW_CLIENT: "client_create",
}


def permission_for_request_type(request_type: str) -> Permission | None:
    spec = REQUEST_TYPE_PERMISSIONS.get(request_type)
    if not spec:
        return None
    app_label, codename = spec
    return Permission.objects.filter(
        content_type__app_label=app_label,
        codename=codename,
    ).first()


def users_authorized_for_request_type(request_type: str):
    """Active users who may create this master type (superuser or holding add permission)."""
    perm = permission_for_request_type(request_type)
    if perm is None:
        return User.objects.none()
    return (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__permissions=perm) | Q(user_permissions=perm))
        .distinct()
        .order_by("username")
    )


def assignees_for_form_json() -> dict[str, list[dict[str, str | int]]]:
    out: dict[str, list[dict[str, str | int]]] = {}
    for request_type in REQUEST_TYPE_PERMISSIONS:
        out[request_type] = [
            {"id": u.pk, "label": user_display_label(u)}
            for u in users_authorized_for_request_type(request_type)
        ]
    return out


def user_display_label(user) -> str:
    name = user_display_name(user)
    return name or user.get_username()


def pending_requests_for_creator(user, request_type: str):
    if not user.is_authenticated:
        return MasterRequest.objects.none()
    return (
        MasterRequest.objects.filter(
            assigned_to=user,
            request_type=request_type,
            status=MasterRequest.STATUS_SUBMITTED,
        )
        .select_related("requested_by", "client")
        .order_by("created_at")
    )


def master_request_link_context(request, request_type: str) -> dict:
    pending = list(pending_requests_for_creator(request.user, request_type))
    preselect = (request.GET.get("master_request") or "").strip()
    if preselect.isdigit():
        extra = (
            MasterRequest.objects.filter(
                pk=int(preselect),
                assigned_to=request.user,
                request_type=request_type,
                status=MasterRequest.STATUS_SUBMITTED,
            )
            .select_related("requested_by")
            .first()
        )
        if extra and extra.pk not in {m.pk for m in pending}:
            pending.insert(0, extra)
    return {
        "pending_master_requests": pending,
        "preselect_master_request_id": preselect,
        "master_request_type": request_type,
    }


def _notify(user, *, master_request: MasterRequest, kind: str, message: str) -> None:
    MasterRequestNotification.objects.create(
        user=user,
        master_request=master_request,
        kind=kind,
        message=message,
    )


def notify_on_submit(master_request: MasterRequest) -> None:
    req = master_request
    type_label = req.get_request_type_display()
    by = user_display_label(req.requested_by)
    client_bit = ""
    if req.client_id:
        client_bit = f" for {req.client.client_name}"
    subject_line = (req.subject or "").strip()
    message_body = (req.message or "").strip()
    msg_assignee = (
        f"Master request #{req.pk}: {by} asked you to create {type_label}{client_bit}."
    )
    if subject_line:
        msg_assignee += f" Subject: {subject_line}."
    if message_body:
        msg_assignee += f" Message: {message_body}"
    msg_requester = (
        f"Your master request #{req.pk} ({type_label}) was sent to "
        f"{user_display_label(req.assigned_to)}."
    )
    _notify(
        req.assigned_to,
        master_request=req,
        kind=MasterRequestNotification.KIND_SUBMITTED_ASSIGNEE,
        message=msg_assignee,
    )
    _notify(
        req.requested_by,
        master_request=req,
        kind=MasterRequestNotification.KIND_SUBMITTED_REQUESTER,
        message=msg_requester,
    )


def notify_on_complete(master_request: MasterRequest) -> None:
    type_label = master_request.get_request_type_display()
    by = user_display_label(master_request.completed_by)
    msg = (
        f"Master request #{master_request.pk} ({type_label}) was completed by {by}. "
        f"{master_request.linked_summary()}"
    )
    _notify(
        master_request.requested_by,
        master_request=master_request,
        kind=MasterRequestNotification.KIND_COMPLETED,
        message=msg,
    )


def try_complete_master_request(request, obj, raw_id: str | None, expected_type: str) -> MasterRequest | None:
    """Link a newly created record to a pending request and notify the requester."""
    if not raw_id or not str(raw_id).strip().isdigit():
        return None
    mr = (
        MasterRequest.objects.filter(
            pk=int(raw_id),
            assigned_to=request.user,
            request_type=expected_type,
            status=MasterRequest.STATUS_SUBMITTED,
        )
        .select_related("requested_by")
        .first()
    )
    if mr is None:
        return None
    mr.linked_object = obj
    mr.status = MasterRequest.STATUS_COMPLETED
    mr.completed_by = request.user
    mr.completed_at = timezone.now()
    mr.save(
        update_fields=[
            "content_type",
            "object_id",
            "status",
            "completed_by",
            "completed_at",
            "updated_at",
        ]
    )
    notify_on_complete(mr)
    return mr


def user_can_view_master_requests(user) -> bool:
    """List, detail, and sidebar — staff with client access or any master-create role."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.has_perm("masters.add_masterrequest") or user.has_perm("masters.view_masterrequest"):
        return True
    if user.has_perm("masters.view_client"):
        return True
    return user_sees_assigned_queue(user)


def user_can_submit_master_requests(user) -> bool:
    """Submit new master requests (most office staff)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.has_perm("masters.add_masterrequest"):
        return True
    return user.has_perm("masters.view_client")


def user_sees_assigned_queue(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    for _rt, (app_label, codename) in REQUEST_TYPE_PERMISSIONS.items():
        if user.has_perm(f"{app_label}.{codename}"):
            return True
    return False


def detail_url_for_request(master_request: MasterRequest) -> str:
    return reverse("master_request_detail", kwargs={"pk": master_request.pk})


def accessible_master_requests(user):
    """Master requests the user may view in the inbox panel."""
    qs = MasterRequest.objects.select_related(
        "requested_by",
        "assigned_to",
        "client",
        "completed_by",
    )
    if user.is_superuser:
        return qs
    return qs.filter(Q(requested_by=user) | Q(assigned_to=user))


def panel_requests_for_notifications(user, request_ids: list[int]):
    if not request_ids:
        return MasterRequest.objects.none()
    return accessible_master_requests(user).filter(pk__in=request_ids).order_by("-updated_at")


def notifications_tab_url(*, notif_filter: str = "all", request_id: int | None = None) -> str:
    params: dict[str, str] = {"tab": "notifications"}
    if notif_filter == "unread":
        params["notif_filter"] = "unread"
    if request_id:
        params["request"] = str(request_id)
    return f"{reverse('master_request_list')}?{urlencode(params)}"
