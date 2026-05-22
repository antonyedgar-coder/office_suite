from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.ui_breadcrumbs import breadcrumbs as ui_breadcrumbs

from .forms import MasterRequestForm
from .master_request_service import (
    REQUEST_TYPE_CREATE_URL,
    assignees_for_form_json,
    detail_url_for_request,
    notifications_tab_url,
    notify_on_submit,
    panel_requests_for_notifications,
    user_can_submit_master_requests,
    user_can_view_master_requests,
    user_sees_assigned_queue,
)
from .models import MasterRequest, MasterRequestNotification


def _require_master_request_access(request):
    if not user_can_view_master_requests(request.user):
        raise PermissionDenied


def _mark_request_notifications_read(user, master_request_id: int | None) -> None:
    if not master_request_id:
        return
    MasterRequestNotification.objects.filter(
        user=user,
        master_request_id=master_request_id,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())


@login_required
def master_request_list(request):
    _require_master_request_access(request)
    tab = (request.GET.get("tab") or "mine").strip()
    if tab == "assigned" and not user_sees_assigned_queue(request.user):
        tab = "mine"
    if tab not in ("mine", "assigned", "notifications"):
        tab = "mine"

    unread_notification_count = MasterRequestNotification.objects.filter(
        user=request.user,
        is_read=False,
    ).count()

    my_qs = MasterRequest.objects.none()
    assigned_qs = MasterRequest.objects.none()
    pending_assigned_count = 0
    notifications = MasterRequestNotification.objects.none()
    panel_requests = MasterRequest.objects.none()
    notif_filter = "all"
    selected_request_id = None
    notifications_all_url = notifications_tab_url()
    notifications_unread_url = notifications_tab_url(notif_filter="unread")

    if tab == "notifications":
        notif_filter = (request.GET.get("notif_filter") or "all").strip()
        if notif_filter not in ("all", "unread"):
            notif_filter = "all"
        notif_qs = MasterRequestNotification.objects.filter(user=request.user)
        if notif_filter == "unread":
            notif_qs = notif_qs.filter(is_read=False)
        notifications = list(
            notif_qs.select_related(
                "master_request",
                "master_request__client",
                "master_request__requested_by",
                "master_request__assigned_to",
            ).order_by("-created_at")[:200]
        )
        request_ids = list(
            dict.fromkeys(
                n.master_request_id for n in notifications if n.master_request_id
            )
        )
        panel_requests = panel_requests_for_notifications(request.user, request_ids)
        raw_sel = (request.GET.get("request") or "").strip()
        if raw_sel.isdigit():
            sel_pk = int(raw_sel)
            if panel_requests.filter(pk=sel_pk).exists():
                selected_request_id = sel_pk
    else:
        my_qs = (
            MasterRequest.objects.filter(requested_by=request.user)
            .select_related("assigned_to", "client", "completed_by")
            .order_by("-created_at")[:300]
        )
        if user_sees_assigned_queue(request.user):
            assigned_base = MasterRequest.objects.filter(assigned_to=request.user).exclude(
                status=MasterRequest.STATUS_CANCELLED
            )
            pending_assigned_count = assigned_base.filter(
                status=MasterRequest.STATUS_SUBMITTED
            ).count()
            if tab == "assigned":
                assigned_qs = assigned_base.select_related(
                    "requested_by", "client", "completed_by"
                ).order_by("-created_at")[:300]

    return render(
        request,
        "masters/master_request_list.html",
        {
            "tab": tab,
            "my_requests": my_qs,
            "assigned_requests": assigned_qs,
            "pending_assigned_count": pending_assigned_count,
            "show_assigned_tab": user_sees_assigned_queue(request.user),
            "notifications": notifications,
            "unread_notification_count": unread_notification_count,
            "notif_filter": notif_filter,
            "panel_requests": panel_requests,
            "selected_request_id": selected_request_id,
            "notifications_all_url": notifications_tab_url(
                request_id=selected_request_id
            ),
            "notifications_unread_url": notifications_tab_url(
                notif_filter="unread", request_id=selected_request_id
            ),
            "breadcrumbs": ui_breadcrumbs(("Master requests",)),
        },
    )


@login_required
def master_request_create(request):
    if not user_can_submit_master_requests(request.user):
        raise PermissionDenied
    if request.method == "POST":
        form = MasterRequestForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.requested_by = request.user
            obj.status = MasterRequest.STATUS_SUBMITTED
            obj.save()
            notify_on_submit(obj)
            messages.success(
                request,
                f"Master request #{obj.pk} sent to {obj.assigned_to}.",
            )
            return redirect("master_request_detail", pk=obj.pk)
    else:
        initial = {}
        prefill_type = (request.GET.get("request_type") or "").strip()
        prefill_client = (request.GET.get("client") or "").strip()
        if prefill_type in dict(MasterRequest.REQUEST_TYPE_CHOICES):
            initial["request_type"] = prefill_type
        if prefill_client:
            initial["client"] = prefill_client
        form = MasterRequestForm(user=request.user, initial=initial)

    return render(
        request,
        "masters/master_request_form.html",
        {
            "form": form,
            "assignees_json": assignees_for_form_json(),
            "breadcrumbs": ui_breadcrumbs(
                ("Master requests", "master_request_list"),
                ("New request",),
            ),
        },
    )


@login_required
def master_request_detail(request, pk: int):
    _require_master_request_access(request)
    obj = get_object_or_404(
        MasterRequest.objects.select_related(
            "requested_by",
            "assigned_to",
            "client",
            "completed_by",
            "content_type",
        ),
        pk=pk,
    )
    user = request.user
    if not (
        user.is_superuser
        or obj.requested_by_id == user.pk
        or obj.assigned_to_id == user.pk
    ):
        raise PermissionDenied

    _mark_request_notifications_read(user, obj.pk)

    create_url_name = REQUEST_TYPE_CREATE_URL.get(obj.request_type)
    create_url = ""
    if create_url_name and obj.status == MasterRequest.STATUS_SUBMITTED:
        if user.pk == obj.assigned_to_id or user.is_superuser:
            create_url = reverse(create_url_name)
            if obj.request_type == MasterRequest.TYPE_NEW_TASK and obj.client_id:
                create_url = f"{create_url}?master_request={obj.pk}"
            else:
                create_url = f"{create_url}?master_request={obj.pk}"

    return render(
        request,
        "masters/master_request_detail.html",
        {
            "obj": obj,
            "create_url": create_url,
            "breadcrumbs": ui_breadcrumbs(
                ("Master requests", "master_request_list"),
                (f"Request #{obj.pk}",),
            ),
        },
    )


@login_required
def master_request_notification_list(request):
    """Legacy URL — notifications live on the Master requests page."""
    _require_master_request_access(request)
    notif_filter = request.GET.get("notif_filter") or "all"
    return redirect(notifications_tab_url(notif_filter=notif_filter))


@login_required
@require_POST
def master_request_notification_mark_read(request, pk: int):
    _require_master_request_access(request)
    n = get_object_or_404(MasterRequestNotification, pk=pk, user=request.user)
    _mark_request_notifications_read(request.user, n.master_request_id)
    stay = request.POST.get("stay") == "1"
    if stay or request.headers.get("Accept", "").startswith("application/json"):
        return JsonResponse(
            {
                "ok": True,
                "notification_id": n.pk,
                "request_id": n.master_request_id,
            }
        )
    notif_filter = request.POST.get("notif_filter") or request.GET.get("notif_filter") or "all"
    if n.master_request_id:
        return redirect("master_request_detail", pk=n.master_request_id)
    return redirect(notifications_tab_url(notif_filter=notif_filter))


@login_required
@require_POST
def master_request_notification_mark_all_read(request):
    _require_master_request_access(request)
    now = timezone.now()
    updated = MasterRequestNotification.objects.filter(
        user=request.user,
        is_read=False,
    ).update(is_read=True, read_at=now)
    messages.success(request, f"Marked {updated} notification(s) as read.")
    notif_filter = request.POST.get("notif_filter") or "all"
    request_id = request.POST.get("request")
    sel = int(request_id) if request_id and str(request_id).isdigit() else None
    return redirect(notifications_tab_url(notif_filter=notif_filter, request_id=sel))
