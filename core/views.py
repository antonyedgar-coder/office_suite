import csv
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Subquery, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render

from dirkyc.fy import earliest_next_dirkyc_allowed_date, fy_label_for_date, fy_label_to_date_range
from dirkyc.models import Dir3Kyc
from masters.models import DIRECTOR_ELIGIBLE_CLIENT_TYPES, Client, DirectorMapping
from mis.models import ExpenseDetail, FeesDetail, Receipt

from .activity_log import log_activity_from_request


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    error = None
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=email, password=password)
        if user is None:
            error = "Invalid email or password."
        else:
            login(request, user)
            log_activity_from_request(
                user=user,
                request=request,
                method="POST",
                path=request.path,
                status_code=302,
                description="LOGIN",
            )
            return redirect("dashboard")

    return render(request, "auth/login.html", {"error": error})


@login_required
def logout_view(request):
    if request.user.is_authenticated:
        log_activity_from_request(
            user=request.user,
            request=request,
            method=request.method,
            path=request.path,
            status_code=302,
            description="LOGOUT",
        )
    logout(request)
    return redirect("login")


@login_required
def dashboard_view(request):
    today = date.today()
    fy_label = fy_label_for_date(today)
    fy_range = fy_label_to_date_range(fy_label)
    fy_start, fy_end = fy_range if fy_range else (today, today)

    client_qs = Client.approved_objects()
    client_total = client_qs.count()
    client_type_counts = list(
        client_qs.values("client_type").annotate(count=Count("pk")).order_by("-count", "client_type")
    )

    last_kyc_sq = (
        Dir3Kyc.objects.filter(director=OuterRef("pk")).order_by("-date_done", "-id").values("date_done")[:1]
    )
    director_qs = (
        client_qs.filter(client_type__in=sorted(DIRECTOR_ELIGIBLE_CLIENT_TYPES), is_director=True)
        .exclude(din="")
        .annotate(last_kyc_date=Subquery(last_kyc_sq))
    )
    dir3_total_directors = director_qs.count()
    dir3_pending_count = 0
    for director in director_qs.iterator(chunk_size=256):
        last_done = director.last_kyc_date
        if last_done is None or today >= earliest_next_dirkyc_allowed_date(last_done):
            dir3_pending_count += 1

    mis_filter = {"date__gte": fy_start, "date__lte": fy_end}
    mis_fy_fees = FeesDetail.objects.filter(**mis_filter).aggregate(
        total=Sum("fees_amount"),
        gst=Sum("gst_amount"),
    )
    fees_sum = (mis_fy_fees["total"] or Decimal("0")) + (mis_fy_fees["gst"] or Decimal("0"))
    mis_fy_receipts = Receipt.objects.filter(**mis_filter).aggregate(total=Sum("amount_received"))["total"] or Decimal(
        "0"
    )
    mis_fy_expenses = ExpenseDetail.objects.filter(**mis_filter).aggregate(total=Sum("expenses_paid"))[
        "total"
    ] or Decimal("0")

    return render(
        request,
        "dashboard.html",
        {
            "today": today,
            "client_total": client_total,
            "client_type_counts": client_type_counts,
            "dir3_pending_count": dir3_pending_count,
            "dir3_total_directors": dir3_total_directors,
            "mis_fy_label": fy_label,
            "mis_fy_period_start": fy_start,
            "mis_fy_period_end": fy_end,
            "mis_fy_fees": fees_sum,
            "mis_fy_receipts": mis_fy_receipts,
            "mis_fy_expenses": mis_fy_expenses,
            "director_mapping_count": DirectorMapping.objects.count(),
        },
    )


@login_required
def activity_log_list(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    from core.models import ActivityLog

    paginator = Paginator(ActivityLog.objects.all(), 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/activity_log_list.html", {"page_obj": page_obj})


@login_required
def activity_log_csv(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    from core.models import ActivityLog

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="activity-log.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["created_at", "user_email", "method", "status_code", "path", "description", "ip_address"])
    for row in ActivityLog.objects.all().order_by("-created_at")[:100_000]:
        writer.writerow(
            [
                row.created_at.isoformat(sep=" ", timespec="seconds"),
                row.user_email,
                row.method,
                row.status_code if row.status_code is not None else "",
                row.path,
                row.description,
                row.ip_address or "",
            ]
        )
    return response


@login_required
def reset_test_data(request):
    """
    Superuser-only: delete local test data (clients, tasks, MIS, users, etc.).
    """
    if not request.user.is_superuser:
        raise PermissionDenied

    from core.reset_data import WipeOptions, count_local_data, wipe_local_data

    counts = count_local_data()

    if request.method == "POST" and request.POST.get("confirm") == "1":
        delete_all = request.POST.get("delete_all") == "1"
        if delete_all:
            options = WipeOptions(
                mis=True,
                director_mapping=True,
                dir3kyc=True,
                clients=True,
                client_groups=True,
                tasks=True,
                activity_log=True,
                delete_users=True,
                users_keep_ids={request.user.pk},
            )
        else:
            delete_clients = request.POST.get("delete_clients") == "1"
            options = WipeOptions(
                mis=request.POST.get("delete_mis") == "1" or delete_clients,
                director_mapping=request.POST.get("delete_director_mapping") == "1" or delete_clients,
                dir3kyc=request.POST.get("delete_dir3kyc") == "1" or delete_clients,
                clients=delete_clients,
                client_groups=request.POST.get("delete_client_groups") == "1",
                tasks=request.POST.get("delete_tasks") == "1" or delete_clients,
                activity_log=request.POST.get("delete_activity_log") == "1",
                delete_users=request.POST.get("delete_users") == "1",
                users_keep_ids={request.user.pk},
            )

        if not any(
            [
                options.mis,
                options.director_mapping,
                options.dir3kyc,
                options.clients,
                options.client_groups,
                options.tasks,
                options.activity_log,
                options.delete_users,
            ]
        ):
            messages.error(request, "Please select at least one dataset to delete.")
            return redirect("reset_test_data")

        deleted = wipe_local_data(options)
        parts = [f"{k}={v}" for k, v in sorted(deleted.items()) if v]
        messages.success(request, "Deleted: " + (", ".join(parts) if parts else "nothing"))
        return redirect("dashboard")

    return render(request, "admin_tools/reset_test_data.html", {"counts": counts})


def permission_denied_view(request, exception):
    message = str(exception) if exception else "You do not have permission to access this page."
    return render(request, "403.html", {"message": message}, status=403)
