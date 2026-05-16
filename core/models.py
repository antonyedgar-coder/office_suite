from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from .branch_access import EMPLOYEE_BRANCH_ACCESS_CHOICES


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, username=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(_("email address"), unique=True)
    force_password_change = models.BooleanField(
        default=False,
        help_text="If true, user must change password before using the app (first login after invite).",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.email


class Employee(models.Model):
    """Profile linked 1:1 to login user (official email = username = User.email)."""

    USER_TYPE_EMPLOYEE = "employee"
    USER_TYPE_CLIENT = "client"
    USER_TYPE_CHOICES = [
        (USER_TYPE_EMPLOYEE, "Employee"),
        (USER_TYPE_CLIENT, "Client"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="employee_profile",
    )
    user_type = models.CharField(
        "Type of user",
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default=USER_TYPE_EMPLOYEE,
        db_index=True,
    )
    linked_client = models.ForeignKey(
        "masters.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_users",
        help_text="For Client-type users: Client Master record this login is tied to.",
    )
    full_name = models.CharField(max_length=200)
    contact_no = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=500, blank=True)
    date_of_joining = models.DateField(
        null=True,
        blank=True,
        help_text="Required for employees; optional for client portal users (filled from Client Master when blank).",
    )
    contact_person = models.CharField(
        max_length=200,
        blank=True,
        help_text="Emergency / alternate contact name",
    )
    aadhar_no = models.CharField(max_length=12, blank=True)
    branch_access = models.CharField(
        "Branch access",
        max_length=32,
        choices=EMPLOYEE_BRANCH_ACCESS_CHOICES,
        blank=True,
        default="",
        help_text="All branches, or restrict to Trivandrum or Nagercoil only.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.user.email})"


class ActivityLog(models.Model):
    """Append-only audit trail of significant actions (superuser-visible only in UI)."""

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    user_email = models.EmailField(blank=True, db_index=True)
    method = models.CharField(max_length=16, db_index=True)
    path = models.CharField(max_length=512)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        who = self.user_email or (self.user.email if self.user_id else "—")
        return f"{who} {self.method} {self.path}"

