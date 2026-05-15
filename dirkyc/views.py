from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import require_perm

from .forms import Dir3KycForm
from .models import Dir3Kyc


def _search_q(request) -> str:
    return (request.GET.get("q") or "").strip().upper()


@require_perm("dirkyc.view_dir3kyc")
def dir3kyc_list(request):
    q = _search_q(request)
    qs = Dir3Kyc.objects.select_related("director").all()
    if q:
        qs = qs.filter(
            Q(director__client_name__icontains=q)
            | Q(director__din__icontains=q)
            | Q(director__client_id__icontains=q)
            | Q(srn__icontains=q)
        )
    qs = qs.order_by("-date_done", "-id")[:500]
    return render(request, "dirkyc/dir3kyc_list.html", {"rows": qs, "q": q})


@require_perm("dirkyc.add_dir3kyc")
def dir3kyc_create(request):
    if request.method == "POST":
        form = Dir3KycForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "DIR-3 KYC record saved.")
            return redirect("dirkyc_list")
    else:
        form = Dir3KycForm()
    return render(request, "dirkyc/dir3kyc_form.html", {"form": form, "mode": "create"})


@require_perm("dirkyc.change_dir3kyc")
def dir3kyc_edit(request, pk: int):
    obj = get_object_or_404(Dir3Kyc, pk=pk)
    if request.method == "POST":
        form = Dir3KycForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "DIR-3 KYC record updated.")
            return redirect("dirkyc_list")
    else:
        form = Dir3KycForm(instance=obj)
    return render(request, "dirkyc/dir3kyc_form.html", {"form": form, "mode": "edit", "obj": obj})


@require_perm("dirkyc.delete_dir3kyc")
def dir3kyc_delete(request, pk: int):
    obj = get_object_or_404(Dir3Kyc, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "DIR-3 KYC record deleted.")
        return redirect("dirkyc_list")
    return render(request, "dirkyc/dir3kyc_confirm_delete.html", {"obj": obj})
