from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404, redirect, render

from .group_forms import GroupAccessForm


def _superuser(u):
    return u.is_authenticated and u.is_superuser


@user_passes_test(_superuser)
def group_list(request):
    groups = Group.objects.prefetch_related("permissions").order_by("name")
    return render(
        request,
        "access/group_list.html",
        {"groups": groups, "user_management_section": "groups"},
    )


@user_passes_test(_superuser)
def group_create(request):
    if request.method == "POST":
        form = GroupAccessForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Access group created.")
            return redirect("user_group_list")
    else:
        form = GroupAccessForm()
    return render(
        request,
        "access/group_form.html",
        {"form": form, "mode": "create", "user_management_section": "groups"},
    )


@user_passes_test(_superuser)
def group_edit(request, pk: int):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        form = GroupAccessForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, "Access group updated.")
            return redirect("user_group_list")
    else:
        form = GroupAccessForm(instance=group)
    return render(
        request,
        "access/group_form.html",
        {
            "form": form,
            "mode": "edit",
            "group": group,
            "user_management_section": "groups",
        },
    )


@user_passes_test(_superuser)
def group_delete(request, pk: int):
    group = get_object_or_404(Group, pk=pk)
    if request.method == "POST":
        name = group.name
        group.delete()
        messages.success(request, f'Access group "{name}" deleted.')
        return redirect("user_group_list")
    return render(
        request,
        "access/group_confirm_delete.html",
        {"group": group, "user_management_section": "groups"},
    )
