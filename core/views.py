import csv

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, OuterRef, Subquery, Sum
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render, redirect

from datetime import date
from decimal import Decimal

from dirkyc.fy import earliest_next_dirkyc_allowed_date, fy_label_for_date, fy_start_year
from dirkyc.models import Dir3Kyc
from masters.models import Client, DIRECTOR_ELIGIBLE_CLIENT_TYPES, DirectorMapping
from mis.models import ExpenseDetail, FeesDetail, Receipt


def permission_denied_view(request, exception=None):
    return render(
        request,
        "403.html",
        {
            "message": "You do not have permission to access this page. "
            "Ask a superuser to add you to an access group or assign permissions.",
        },
        status=403,
    )

User = get_user_model()


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    error = None
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=email, password=password)
        if user is None:
            try:
                u = User.objects.get(email__iexact=email)
                if not u.is_active:
                    error = "This account is inactive. Contact your administrator."
                else:
                    error = "Invalid email or password."
            except User.DoesNotExist:
                error = "Invalid email or password."
        else:
            login(request, user)
            from .activity_log import log_activity_from_request

            log_activity_from_request(
                user=user,
                request=request,
                method="LOGIN",
                path=request.path,
                status_code=302,
                description="Signed in",
            )
            return redirect("dashboard")

    return render(request, "auth/login.html", {"error": error})


def logout_view(request):
    if request.user.is_authenticated:
        from .activity_log import log_activity_from_request

        log_activity_from_request(
            user=request.user,
            request=request,
            method="LOGOUT",
            path=request.path,
            status_code=302,
            description="Signed out",
        )
    logout(request)
    return redirect("login")


@login_required
def dashboard_view(request):
    today = date.today()

    # Clients by type
    from core.branch_access import approved_clients_for_user, filter_mis_qs

    client_type_counts_qs = (
        approved_clients_for_user(request.user).values("client_type")
        .annotate(count=Count("client_id"))
        .order_by("client_type")
    )
    client_type_counts = [{"type": r["client_type"] or "—", "count": r["count"]} for r in client_type_counts_qs]
    client_total = sum(r["count"] for r in client_type_counts)

    # MIS totals for current Indian FY (Apr 1 .. today), all approved clients — same scope as MIS reports
    cur_fy = fy_start_year(today)
    fy_apr1 = date(cur_fy, 4, 1)
    fy_mar31 = date(cur_fy + 1, 3, 31)
    fy_through = today if today <= fy_mar31 else fy_mar31
    mis_fy_label = fy_label_for_date(today)
    fy_mis_filter = dict(
        client__approval_status=Client.APPROVED,
        date__gte=fy_apr1,
        date__lte=fy_through,
    )

    def _dec_sum(qs, field: str):
        v = qs.aggregate(t=Sum(field))["t"]
        if v is None:
            return Decimal("0.00")
        return Decimal(v)

    mis_fy_fees = _dec_sum(
        filter_mis_qs(FeesDetail.objects.filter(**fy_mis_filter), request.user),
        "total_amount",
    )
    mis_fy_receipts = _dec_sum(
        filter_mis_qs(Receipt.objects.filter(**fy_mis_filter), request.user),
        "amount_received",
    )
    mis_fy_expenses = _dec_sum(
        filter_mis_qs(ExpenseDetail.objects.filter(**fy_mis_filter), request.user),
        "expenses_paid",
    )
    from core.branch_access import filter_director_mapping_qs

    director_mapping_count = filter_director_mapping_qs(DirectorMapping.objects.all(), request.user).count()

    # DIR-3 KYC pending count as on date:
    # pending if never filed OR as_of >= earliest_next_allowed_from(last filing)
    last_sq = (
        Dir3Kyc.objects.filter(director=OuterRef("pk"))
        .order_by("-date_done", "-id")
        .values("date_done")[:1]
    )
    directors = (
        approved_clients_for_user(request.user)
        .filter(client_type__in=sorted(DIRECTOR_ELIGIBLE_CLIENT_TYPES), is_director=True)
        .exclude(din="")
        .annotate(last_kyc_date=Subquery(last_sq))
        .values("din", "last_kyc_date")
    )
    pending = 0
    total_directors = 0
    for d in directors:
        total_directors += 1
        ld = d.get("last_kyc_date")
        if ld is None:
            pending += 1
            continue
        if today >= earliest_next_dirkyc_allowed_date(ld):
            pending += 1

    return render(
        request,
        "dashboard.html",
        {
            "client_type_counts": client_type_counts,
            "client_total": client_total,
            "mis_fy_label": mis_fy_label,
            "mis_fy_period_start": fy_apr1,
            "mis_fy_period_end": fy_through,
            "mis_fy_fees": mis_fy_fees,
            "mis_fy_receipts": mis_fy_receipts,
            "mis_fy_expenses": mis_fy_expenses,
            "director_mapping_count": director_mapping_count,
            "dir3_pending_count": pending,
            "dir3_total_directors": total_directors,
            "today": today,
        },
    )


@login_required
def activity_log_list(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    from .models import ActivityLog

    qs = ActivityLog.objects.select_related("user").order_by("-created_at")
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    return render(
        request,
        "core/activity_log_list.html",
        {"page_obj": page_obj},
    )


@login_required
def activity_log_csv(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    from .models import ActivityLog

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="activity-log.csv"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(
        ["created_at", "user_email", "method", "status_code", "path", "description", "ip_address"]
    )

    qs = ActivityLog.objects.order_by("-created_at")[:100_000]
    for row in qs.iterator(chunk_size=500):
        desc = (row.description or "").replace("\n", " ").replace("\r", " ")
        writer.writerow(
            [
                row.created_at.isoformat() if row.created_at else "",
                row.user_email,
                row.method,
                row.status_code if row.status_code is not None else "",
                row.path,
                desc,
                row.ip_address or "",
            ]
        )

    return response


@login_required
def reset_test_data(request):
    """
    Superuser-only: deletes transactional "test" data in one click.
    Keeps Client Master intentionally (so users can re-upload MIS / mappings / KYC
    without breaking logins or reference data).
    """
    if not request.user.is_superuser:
        raise PermissionDenied

    from mis.models import ExpenseDetail, FeesDetail, Receipt
    from masters.models import Client, ClientSequence, DirectorMapping
    from dirkyc.models import Dir3Kyc

    counts = {
        "clients": Client.objects.count(),
        "fees": FeesDetail.objects.count(),
        "receipts": Receipt.objects.count(),
        "expenses": ExpenseDetail.objects.count(),
        "director_mappings": DirectorMapping.objects.count(),
        "dir3kyc": Dir3Kyc.objects.count(),
    }

    if request.method == "POST" and request.POST.get("confirm") == "1":
        delete_mis = request.POST.get("delete_mis") == "1"
        delete_dm = request.POST.get("delete_director_mapping") == "1"
        delete_kyc = request.POST.get("delete_dir3kyc") == "1"
        delete_clients = request.POST.get("delete_clients") == "1"

        # If deleting Client Master, we must clear all dependent data first to avoid PROTECT errors.
        if delete_clients:
            delete_mis = True
            delete_dm = True
            delete_kyc = True

        if not (delete_mis or delete_dm or delete_kyc or delete_clients):
            messages.error(request, "Please select at least one dataset to delete.")
            return redirect("reset_test_data")

        with transaction.atomic():
            deleted = {}
            if delete_mis:
                deleted["fees"] = FeesDetail.objects.all().delete()[0]
                deleted["receipts"] = Receipt.objects.all().delete()[0]
                deleted["expenses"] = ExpenseDetail.objects.all().delete()[0]
            if delete_dm:
                deleted["director_mappings"] = DirectorMapping.objects.all().delete()[0]
            if delete_kyc:
                deleted["dir3kyc"] = Dir3Kyc.objects.all().delete()[0]
            if delete_clients:
                deleted["client_sequences"] = ClientSequence.objects.all().delete()[0]
                deleted["clients"] = Client.objects.all().delete()[0]

        parts = [f"{k}={v}" for k, v in deleted.items()]
        messages.success(request, "Deleted test data: " + ", ".join(parts))
        return redirect("dashboard")

    return render(request, "admin_tools/reset_test_data.html", {"counts": counts})

