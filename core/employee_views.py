from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .decorators import require_perm
from .employee_forms import EmployeeCreateForm, EmployeeEditForm, FirstPasswordChangeForm
from .models import Employee

User = get_user_model()


def sync_employee_from_client_master(employee: Employee) -> None:
    """Refresh profile fields from Client Master for client-type users."""
    if employee.user_type != Employee.USER_TYPE_CLIENT or not employee.linked_client_id:
        return
    c = employee.linked_client
    employee.full_name = c.client_name
    employee.contact_no = (c.mobile or "").strip()
    employee.address = (c.address or "").strip()
    employee.contact_person = (c.contact_person or "").strip()
    employee.aadhar_no = ""
    if not employee.date_of_joining and c.created_at:
        employee.date_of_joining = c.created_at.date()
    employee.save()
    em = (c.email or "").strip().lower()
    if em and employee.user.email.lower() != em:
        employee.user.email = em
        employee.user.username = em
        employee.user.save(update_fields=["email", "username"])


@require_perm("core.view_employee")
def employee_list(request):
    employees = Employee.objects.select_related("user", "linked_client").order_by("full_name")
    return render(
        request,
        "employees/employee_list.html",
        {"employees": employees, "user_management_section": "users"},
    )


@require_perm("core.add_employee")
def employee_create(request):
    if request.method == "POST":
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["official_email"]
            is_active = form.cleaned_data.get("is_active", True)
            pwd = form.cleaned_data["password"]
            linked_pk = form.cleaned_data.get("_linked_client_pk")

            user = User.objects.create_user(
                email=email,
                password=pwd,
                is_active=is_active,
                is_staff=False,
                is_superuser=False,
                force_password_change=form.cleaned_data.get("force_password_change", False),
            )
            user.groups.set(form.cleaned_data["groups"])
            user.user_permissions.set(form.cleaned_data["user_permissions"])

            Employee.objects.create(
                user=user,
                user_type=form.cleaned_data["user_type"],
                linked_client_id=linked_pk,
                full_name=form.cleaned_data["full_name"].strip(),
                contact_no=form.cleaned_data.get("contact_no") or "",
                address=form.cleaned_data.get("address") or "",
                date_of_joining=form.cleaned_data["date_of_joining"],
                contact_person=form.cleaned_data.get("contact_person") or "",
                aadhar_no=(form.cleaned_data.get("aadhar_no") or "").replace(" ", ""),
            )
            messages.success(
                request,
                f"User created. They can sign in with {email} using the password you set.",
            )
            return redirect("user_list")
    else:
        form = EmployeeCreateForm()

    return render(
        request,
        "employees/employee_form.html",
        {
            "form": form,
            "mode": "create",
            "user_management_section": "users",
        },
    )


@require_perm("core.change_employee")
def employee_edit(request, pk: int):
    employee = get_object_or_404(
        Employee.objects.select_related("user", "linked_client"),
        pk=pk,
    )
    user = employee.user

    if (
        request.method != "POST"
        and employee.user_type == Employee.USER_TYPE_CLIENT
        and employee.linked_client_id
    ):
        sync_employee_from_client_master(employee)
        employee.refresh_from_db()
        user.refresh_from_db()

    if request.method == "POST":
        form = EmployeeEditForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            user.is_active = form.cleaned_data.get("is_active", True)
            user.force_password_change = form.cleaned_data.get("force_password_change", False)
            user.groups.set(form.cleaned_data["groups"])
            user.user_permissions.set(form.cleaned_data["user_permissions"])
            np = (form.cleaned_data.get("new_password") or "").strip()
            if np:
                user.set_password(np)
            user.save()
            sync_employee_from_client_master(employee)
            messages.success(request, "User updated.")
            return redirect("user_list")
    else:
        form = EmployeeEditForm(instance=employee)

    return render(
        request,
        "employees/employee_form.html",
        {
            "form": form,
            "mode": "edit",
            "employee": employee,
            "official_email": user.email,
            "user_management_section": "users",
        },
    )


@login_required
def first_password_change(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if not request.user.force_password_change:
        return redirect("dashboard")

    if request.method == "POST":
        form = FirstPasswordChangeForm(request.POST)
        if form.is_valid():
            if not request.user.check_password(form.cleaned_data["current_password"]):
                form.add_error("current_password", "Current password is incorrect.")
            else:
                request.user.set_password(form.cleaned_data["new_password"])
                request.user.force_password_change = False
                request.user.save(update_fields=["password", "force_password_change"])
                messages.success(request, "Password updated. You can continue using the app.")
                return redirect("dashboard")
    else:
        form = FirstPasswordChangeForm()

    return render(request, "auth/first_password_change.html", {"form": form})
