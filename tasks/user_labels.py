from django.contrib.auth import get_user_model

from core.models import Employee

User = get_user_model()


def staff_users_queryset():
    return (
        User.objects.filter(
            is_active=True,
            employee_profile__user_type=Employee.USER_TYPE_EMPLOYEE,
        )
        .select_related("employee_profile")
        .order_by("employee_profile__full_name", "email")
    )


def user_display_label(user: User) -> str:
    emp = _employee_profile(user)
    name = (emp.full_name if emp else "").strip() or user.get_full_name() or user.email
    return f"{name} — {user.email}"


def _employee_profile(user: User):
    if user is None or not hasattr(user, "employee_profile"):
        return None
    return user.employee_profile


def _person_name(user: User) -> str:
    emp = _employee_profile(user)
    return ((emp.full_name if emp else "") or user.get_full_name() or "").strip()


def user_person_name(user: User | None) -> str:
    """Display name from user management (Employee full name), not login email."""
    if user is None:
        return ""
    return _person_name(user) or (user.email or "")


def short_code_candidates(user: User) -> list[str]:
    """Preferred 2-character codes, longest uniqueness attempted first."""
    name = _person_name(user)
    parts = [p for p in name.split() if p]
    cands: list[str] = []
    if len(parts) >= 2:
        cands.append((parts[0][0] + parts[-1][0]).upper())
    if parts and len(parts[0]) >= 2:
        cands.append(parts[0][:2].upper())
    if len(parts) >= 2 and len(parts[1]) >= 1:
        cands.append((parts[0][0] + parts[1][0]).upper())
    if len(parts) >= 3:
        cands.append((parts[0][0] + parts[2][0]).upper())
    local = (user.email or "").split("@")[0].upper()
    if len(local) >= 2:
        cands.append(local[:2])
    if parts:
        cands.append(parts[0][0].upper() + (parts[-1][1].upper() if len(parts[-1]) > 1 else "X"))
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        c = (c or "").upper()[:2]
        if len(c) == 2 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def short_code_for_user(user: User, reserved: set[str]) -> str:
    for code in short_code_candidates(user):
        if code not in reserved:
            reserved.add(code)
            return code
    for i in range(26):
        for j in range(26):
            code = chr(65 + i) + chr(65 + j)
            if code not in reserved:
                reserved.add(code)
                return code
    code = f"U{user.pk % 10}"
    reserved.add(code)
    return code


def build_short_codes_for_users(users) -> dict[int, str]:
    reserved: set[str] = set()
    return {u.pk: short_code_for_user(u, reserved) for u in users}
