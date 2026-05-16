import re
from datetime import date
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


BRANCH_CHOICES = [
    ("Trivandrum", "Trivandrum"),
    ("Nagercoil", "Nagercoil"),
]

CLIENT_TYPES = [
    ("Individual", "Individual"),
    ("Partnership", "Partnership"),
    ("LLP", "LLP"),
    ("Branch", "Branch"),
    ("Private Limited", "Private Limited"),
    ("Public Limited", "Public Limited"),
    ("Nidhi Co", "Nidhi Co"),
    ("FPO", "FPO"),
    ("Trust", "Trust"),
    ("Sec 8 Co", "Sec 8 Co"),
    ("Society", "Society"),
    ("Foreign Citizen", "Foreign Citizen"),
    ("None", "None"),
]

CIN_APPLICABLE = {
    "Private Limited",
    "Public Limited",
    "FPO",
    "Sec 8 Co",
    "Nidhi Co",
}

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
LLPIN_RE = re.compile(r"^[A-Z]{3}-[0-9]{4}$")
CIN_RE = re.compile(r"^[A-Z0-9]{21}$")
DIN_RE = re.compile(r"^[0-9]{8}$")
# Client / trade names and contact person: letters (Unicode), digits, spaces, and common punctuation only.
CLIENT_NAME_TEXT_RE = re.compile(r"^[\w\s\.\,'&()/:+*#%=\-]+$", re.UNICODE)
# Passport: compact alphanumeric after removing spaces/hyphens (stored compact, uppercased).
PASSPORT_RE = re.compile(r"^[A-Z0-9]{6,24}$")
AADHAAR_RE = re.compile(r"^[0-9]{12}$")

PAN_OPTIONAL_CLIENT_TYPES = frozenset({"None", "Foreign Citizen"})
PASSPORT_AADHAAR_ALLOWED_TYPES = frozenset({"Individual", "Foreign Citizen"})

# 4th PAN character (1-based index 4 → 0-based index 3) constrains allowed client types when PAN is present and valid.
PAN_FOURTH_CHAR_CLIENT_TYPES: dict[str, frozenset[str]] = {
    "P": frozenset({"Individual", "None", "Foreign Citizen"}),
    "T": frozenset({"Trust", "None"}),
    "C": frozenset(
        {"Private Limited", "FPO", "Nidhi Co", "Sec 8 Co", "Public Limited", "None"}
    ),
    "F": frozenset({"LLP", "Partnership", "None"}),
}

_NAME_KEYWORD_TYPE_PATTERNS: list[tuple[re.Pattern[str], frozenset[str]]] = [
    (re.compile(r"\bPRIVATE\s+LIMITED\b"), frozenset({"Private Limited"})),
    (re.compile(r"\bLLP\b"), frozenset({"LLP"})),
    (re.compile(r"\bNIDHI\b"), frozenset({"Nidhi Co"})),
    (re.compile(r"\bTRUST\b"), frozenset({"Trust"})),
    (re.compile(r"\bFARMER\b"), frozenset({"FPO"})),
]

_LIMITED_WORD_RE = re.compile(r"\bLIMITED\b")
_PRIVATE_LIMITED_RE = re.compile(r"\bPRIVATE\s+LIMITED\b")
_NIDHI_LIMITED_RE = re.compile(r"\bNIDHI\s+LIMITED\b")


def _client_types_required_by_name(name_upper: str) -> frozenset[str] | None:
    """
    If the client name contains keywords that fix the client type, return the allowed types
    (intersection of all triggered rules). None means no keyword rule applies.
    Empty frozenset means the name triggers conflicting requirements.
    """
    reqs: list[frozenset[str]] = []
    farmer_hit = False
    for pat, allowed in _NAME_KEYWORD_TYPE_PATTERNS:
        if pat.search(name_upper):
            reqs.append(allowed)
            if "FPO" in allowed:
                farmer_hit = True
    if (
        _LIMITED_WORD_RE.search(name_upper)
        and not _PRIVATE_LIMITED_RE.search(name_upper)
        and not _NIDHI_LIMITED_RE.search(name_upper)
        and not farmer_hit
    ):
        reqs.append(frozenset({"Public Limited"}))
    if not reqs:
        return None
    inter = reqs[0]
    for s in reqs[1:]:
        inter = inter & s
    return inter


def normalize_din_from_import_value(value) -> str:
    """
    Normalize DIN from CSV/Excel cells: trim, undo trailing '.0' from float export,
    left-pad with zeros when the value is all digits and shorter than 8 (Excel drops leading zeros).
    """
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        s = str(value)
        if s.isdigit() and len(s) < 8:
            return s.zfill(8)
        return s
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        rounded = round(value)
        if abs(value - rounded) > 1e-9:
            return str(value).strip()
        s = str(int(rounded))
        if s.isdigit() and len(s) < 8:
            return s.zfill(8)
        return s
    s = str(value).strip()
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".", 1)[0]
    if s.isdigit() and len(s) < 8:
        return s.zfill(8)
    return s


def _first_letter_a_to_z(text: str, *, default: str = "X") -> str:
    """First A–Z letter in text (uppercase); used for auto client/group ID prefixes."""
    for ch in (text or "").strip().upper():
        if "A" <= ch <= "Z":
            return ch
    return default


def _first_letter_for_group_id(name: str) -> str:
    """First A–Z letter of normalized name; used in auto group IDs (GR + letter + serial)."""
    letter = _first_letter_a_to_z(name, default="")
    return letter


class ClientSequence(models.Model):
    """Per name+branch prefix counter (client_id format: {L}{B}{NNNN}, e.g. AN0001)."""

    prefix = models.CharField(max_length=2, primary_key=True)
    last_value = models.PositiveIntegerField(default=0)


class GroupSequence(models.Model):
    """Per-letter counter for ClientGroup.group_id (format GR{L}{NNN})."""

    letter = models.CharField(max_length=1, primary_key=True)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Group ID sequence"
        verbose_name_plural = "Group ID sequences"

    @classmethod
    def allocate_next(cls, letter: str) -> str:
        from django.db import transaction

        lt = letter.upper()
        if len(lt) != 1 or not ("A" <= lt <= "Z"):
            raise ValueError("Group ID letter must be a single A–Z character.")
        with transaction.atomic():
            row, _ = cls.objects.select_for_update().get_or_create(letter=lt, defaults={"last_value": 0})
            row.last_value += 1
            row.save(update_fields=["last_value"])
            n = row.last_value
        return f"GR{lt}{n:03d}"


class ClientGroup(models.Model):
    """Group Master — clients link here instead of typing a free-text group name."""

    group_id = models.CharField(
        max_length=12,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name="Group ID",
    )
    name = models.CharField(max_length=120, unique=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Group"
        verbose_name_plural = "Groups"

    def __str__(self) -> str:
        if self.group_id:
            return f"{self.group_id} · {self.name}"
        return self.name or "—"

    def clean(self):
        self.name = (self.name or "").strip().upper()
        if not self.name:
            raise ValidationError({"name": "Group name is required."})
        if not _first_letter_for_group_id(self.name):
            raise ValidationError(
                {
                    "name": "Group name must contain at least one letter A–Z "
                    "(used to build the auto Group ID, e.g. GRJ001)."
                }
            )
        if not CLIENT_NAME_TEXT_RE.match(self.name):
            raise ValidationError(
                {
                    "name": "Group name may only contain letters, numbers, spaces, and common punctuation "
                    "(. , ' & ( ) / : + * # % = -)."
                }
            )

    def save(self, *args, **kwargs):
        if self._state.adding and not self.group_id:
            letter = _first_letter_for_group_id((self.name or "").strip().upper())
            if not letter:
                raise ValidationError(
                    {"name": "Group name must contain at least one letter A–Z for ID generation."}
                )
            self.group_id = GroupSequence.allocate_next(letter)
        super().save(*args, **kwargs)


class Client(models.Model):
    """Client Master record. Non–superuser creates/updates require approval before use in MIS / mappings / KYC."""

    APPROVED = "approved"
    PENDING = "pending"
    APPROVAL_STATUS_CHOICES = [
        (APPROVED, "Approved"),
        (PENDING, "Pending approval"),
    ]

    # Client ID like AN0001 (name letter + branch letter + 4-digit serial)
    client_id = models.CharField(max_length=6, primary_key=True, editable=False)

    approval_status = models.CharField(
        max_length=16,
        choices=APPROVAL_STATUS_CHOICES,
        default=APPROVED,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clients_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clients_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    client_type = models.CharField(max_length=32, choices=CLIENT_TYPES)
    branch = models.CharField(max_length=32, choices=BRANCH_CHOICES, default="Trivandrum")
    client_name = models.CharField(max_length=200)
    client_group = models.ForeignKey(
        ClientGroup,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="clients",
        verbose_name="Group",
    )
    file_no = models.CharField("File No", max_length=120, blank=True)

    pan = models.CharField(max_length=10, blank=True)
    passport_no = models.CharField("Passport No", max_length=24, blank=True)
    aadhaar_no = models.CharField("Aadhaar No", max_length=12, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    dob = models.DateField("DOB", null=True, blank=True)
    llpin = models.CharField(max_length=8, blank=True)
    cin = models.CharField(max_length=21, blank=True)

    is_director = models.BooleanField(default=False)
    din = models.CharField(max_length=8, blank=True)

    address = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    mobile = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["client_name"]),
            models.Index(fields=["pan"]),
            models.Index(fields=["passport_no"]),
        ]
        permissions = [
            ("approve_client", "Can approve client master records"),
        ]

    @classmethod
    def approved_objects(cls):
        """Clients cleared for MIS, director mapping, DIR-3 KYC, and reports pickers."""
        return cls.objects.filter(approval_status=cls.APPROVED)

    def clean(self):
        # Normalize to uppercase for specified fields
        self.client_name = (self.client_name or "").strip().upper()
        self.file_no = (self.file_no or "").strip()
        self.pan = (self.pan or "").strip().upper()
        self.gstin = (self.gstin or "").strip().upper()
        self.llpin = (self.llpin or "").strip().upper()
        self.cin = (self.cin or "").strip().upper()
        self.din = normalize_din_from_import_value((self.din or "").strip())
        pass_raw = (self.passport_no or "").strip()
        self.passport_no = re.sub(r"[\s\-]", "", pass_raw.upper())
        self.aadhaar_no = re.sub(r"\D", "", (self.aadhaar_no or "").strip())
        self.contact_person = (self.contact_person or "").strip()

        errors: dict[str, list[str]] = {}

        if not self.client_name:
            errors.setdefault("client_name", []).append("Client Name is required.")
        elif not CLIENT_NAME_TEXT_RE.match(self.client_name):
            errors.setdefault("client_name", []).append(
                "Client name may only contain letters, numbers, spaces, and common punctuation "
                "(. , ' & ( ) / : + * # % = -)."
            )
        if self.contact_person and not CLIENT_NAME_TEXT_RE.match(self.contact_person):
            errors.setdefault("contact_person", []).append(
                "Contact person may only contain letters, numbers, spaces, and common punctuation "
                "(. , ' & ( ) / : + * # % = -)."
            )

        if self.client_group_id and not self.client_group.is_active:
            errors.setdefault("client_group", []).append(
                "This group is inactive. Choose an active group or clear the group."
            )

        # Name keywords imply client type.
        #
        # IMPORTANT business override:
        # If PAN is blank and the name contains keywords like PRIVATE LIMITED/TRUST/FARMER/NIDHI/LLP/LIMITED,
        # then Client Type must be NONE (do not force company types without PAN).
        name_type_req = _client_types_required_by_name(self.client_name)
        if not self.pan and name_type_req is not None:
            if self.client_type != "None":
                errors.setdefault("client_type", []).append(
                    "Since PAN is blank, Client Type must be None (even if the name contains Private Limited / Trust / Farmer / Nidhi / LLP / Limited)."
                )
        elif name_type_req is not None:
            if not name_type_req:
                errors.setdefault("client_name", []).append(
                    "The client name contains keywords that imply conflicting client types "
                    "(for example LLP and Public Limited). Adjust the name or client type."
                )
            elif self.client_type not in name_type_req:
                allowed = ", ".join(sorted(name_type_req))
                errors.setdefault("client_type", []).append(
                    f"Given this client name, Client Type must be {allowed}."
                )

        # Client type → name (when that type is chosen)
        if self.client_type == "Private Limited" and not _PRIVATE_LIMITED_RE.search(self.client_name):
            errors.setdefault("client_name", []).append("Must contain PRIVATE LIMITED.")
        if self.client_type == "Public Limited" and not _LIMITED_WORD_RE.search(self.client_name):
            errors.setdefault("client_name", []).append("Must contain LIMITED as a whole word.")
        if self.client_type == "Nidhi Co" and not re.search(r"\bNIDHI\b", self.client_name):
            errors.setdefault("client_name", []).append("Must contain NIDHI.")
        if self.client_type == "FPO" and not re.search(r"\bFARMER\b", self.client_name):
            errors.setdefault("client_name", []).append("Must contain FARMER.")

        # Passport / Aadhaar (Individual and Foreign Citizen only)
        if self.client_type in PASSPORT_AADHAAR_ALLOWED_TYPES:
            if self.client_type == "Foreign Citizen" and not self.passport_no:
                errors.setdefault("passport_no", []).append("Passport No is mandatory for Foreign Citizen.")
            if self.passport_no and not PASSPORT_RE.match(self.passport_no):
                errors.setdefault("passport_no", []).append(
                    "Passport No must be 6–24 letters or digits (spaces/hyphens are ignored)."
                )
            if self.aadhaar_no and not AADHAAR_RE.match(self.aadhaar_no):
                errors.setdefault("aadhaar_no", []).append("Aadhaar No must be exactly 12 digits when provided.")
        else:
            if self.passport_no:
                errors.setdefault("passport_no", []).append(
                    "Passport No applies only to Individual or Foreign Citizen."
                )
            if self.aadhaar_no:
                errors.setdefault("aadhaar_no", []).append(
                    "Aadhaar No applies only to Individual or Foreign Citizen."
                )

        # PAN rules
        if self.client_type not in PAN_OPTIONAL_CLIENT_TYPES and self.client_type != "Branch" and not self.pan:
            errors.setdefault("pan", []).append("PAN is mandatory (except Client Type None, Foreign Citizen, or Branch).")
        if self.pan and not PAN_RE.match(self.pan):
            errors.setdefault("pan", []).append("PAN must be 10 chars in format AAAAA9999A.")
        if self.pan and self.client_type != "Branch":
            # PAN must be unique for all non-Branch records.
            # Branch records may share PAN with other Branch and non-Branch clients.
            pan_dupe_q = Client.objects.filter(pan=self.pan).exclude(pk=self.pk).exclude(client_type="Branch")
            if pan_dupe_q.exists():
                errors.setdefault("pan", []).append(
                    "PAN already exists for another non-Branch client. Duplicate PAN is allowed only for Client Type Branch."
                )
        if self.pan and PAN_RE.match(self.pan) and self.client_type != "Branch":
            fourth = self.pan[3]
            allowed_by_pan = PAN_FOURTH_CHAR_CLIENT_TYPES.get(fourth)
            if allowed_by_pan is not None and self.client_type not in allowed_by_pan:
                opts = ", ".join(sorted(allowed_by_pan))
                errors.setdefault("client_type", []).append(
                    f"For this PAN (4th character {fourth!r}), Client Type must be one of: {opts}."
                )

        # DOB rules
        if self.dob and self.dob > date.today():
            errors.setdefault("dob", []).append("DOB cannot be in the future.")

        # GSTIN rules
        if self.gstin:
            if len(self.gstin) != 15:
                errors.setdefault("gstin", []).append("GSTIN must be exactly 15 characters.")
            if self.client_type == "Foreign Citizen":
                if self.pan and len(self.gstin) >= 12 and self.gstin[2:12] != self.pan:
                    errors.setdefault("gstin", []).append("GSTIN characters 3–12 must match PAN when PAN is provided.")
            else:
                if not self.pan:
                    errors.setdefault("gstin", []).append("PAN is required if GSTIN is provided.")
                elif len(self.gstin) >= 12:
                    if self.gstin[2:12] != self.pan:
                        errors.setdefault("gstin", []).append("GSTIN characters 3–12 must match PAN exactly.")

        # LLPIN rules
        if self.client_type == "LLP":
            if self.llpin and not LLPIN_RE.match(self.llpin):
                errors.setdefault("llpin", []).append("LLPIN must be in format AAA-9999.")
        else:
            if self.llpin:
                errors.setdefault("llpin", []).append("LLPIN is applicable only for Client Type LLP.")

        # CIN rules
        if self.cin:
            if self.client_type not in CIN_APPLICABLE:
                errors.setdefault("cin", []).append(
                    "CIN is applicable only for Private Limited, Public Limited, FPO, Sec 8 Co, Nidhi Co."
                )
            elif not CIN_RE.match(self.cin):
                errors.setdefault("cin", []).append("CIN must be 21 alphanumeric characters.")

        # DIN rules (Individual and Foreign Citizen; Branch handled above)
        if self.client_type == "Branch":
            if self.is_director:
                errors.setdefault("is_director", []).append(
                    "Is Director cannot be selected when Client Type is Branch."
                )
            if self.din:
                errors.setdefault("din", []).append("DIN cannot be entered when Client Type is Branch.")
        elif self.client_type in ("Individual", "Foreign Citizen"):
            if self.is_director:
                if not self.din:
                    errors.setdefault("din", []).append("DIN is mandatory when Is Director is selected.")
                elif not DIN_RE.match(self.din):
                    errors.setdefault("din", []).append("DIN must be exactly 8 digits.")
            else:
                if self.din:
                    errors.setdefault("din", []).append("DIN should be blank unless Is Director is selected.")
        else:
            if self.is_director:
                errors.setdefault("is_director", []).append(
                    "Is Director applies only to Individual or Foreign Citizen client type."
                )
            if self.din:
                errors.setdefault("din", []).append(
                    "DIN is applicable only for Client Type Individual or Foreign Citizen."
                )

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _client_id_prefix(name_upper: str, branch: str) -> str:
        """First letter of client name + first letter of branch (e.g. AN, AT)."""
        return _first_letter_a_to_z(name_upper) + _first_letter_a_to_z(branch)

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.client_id:
            prefix = self._client_id_prefix(self.client_name, self.branch)
            with transaction.atomic():
                seq, _ = ClientSequence.objects.select_for_update().get_or_create(prefix=prefix)
                seq.last_value += 1
                seq.save(update_fields=["last_value"])
                self.client_id = f"{prefix}{seq.last_value:04d}"
        return super().save(*args, **kwargs)


DIRECTOR_COMPANY_TYPES = {
    "Private Limited",
    "Public Limited",
    "Nidhi Co",
    "FPO",
    "Sec 8 Co",
    "LLP",
}

# Client types allowed as the director side of Director Mapping / DIR-3 (must be marked director with DIN).
DIRECTOR_ELIGIBLE_CLIENT_TYPES = frozenset({"Individual", "Foreign Citizen"})

CESSATION_REASON_CHOICES = [
    ("Resigned", "Resigned"),
    ("Disqualified", "Disqualified"),
    ("Terminated", "Terminated"),
    ("Death", "Death"),
]


class DirectorMapping(models.Model):
    """
    Map a director (Individual or Foreign Citizen) to a company client with appointment/cessation dates.
    Director details live in Client Master; this is only the relationship history.
    """

    director = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="director_roles",
        help_text="Select the director record from Client Master (Individual or Foreign Citizen with DIN).",
    )
    company = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="director_appointments",
        help_text="Select the company (limited list by client type).",
    )
    appointed_date = models.DateField(null=True, blank=True)
    cessation_date = models.DateField(null=True, blank=True)
    reason_for_cessation = models.CharField(
        max_length=32,
        choices=CESSATION_REASON_CHOICES,
        blank=True,
        verbose_name="Reason for cessation",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-appointed_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["director", "company", "appointed_date"],
                condition=models.Q(appointed_date__isnull=False),
                name="uniq_director_company_appointed_date_set",
            ),
        ]

    def clean(self):
        errors: dict[str, list[str]] = {}

        # Director must be Individual or Foreign Citizen + Is Director + DIN present
        if self.director_id:
            if self.director.client_type not in DIRECTOR_ELIGIBLE_CLIENT_TYPES:
                errors.setdefault("director", []).append(
                    "Director must be an Individual or Foreign Citizen client."
                )
            if self.director.approval_status != Client.APPROVED:
                errors.setdefault("director", []).append("Director must be an approved Client Master record.")
            if not self.director.is_director:
                errors.setdefault("director", []).append(
                    "Selected client is not marked as Director in Client Master."
                )
            if not (self.director.din or "").strip():
                errors.setdefault("director", []).append("Director DIN is required in Client Master.")

        # Company must be allowed type
        if self.company_id and self.company.client_type not in DIRECTOR_COMPANY_TYPES:
            errors.setdefault("company", []).append(
                "Company type must be Private Limited, Public Limited, Nidhi Co, FPO, Sec 8 Co or LLP."
            )
        if self.company_id and self.company.approval_status != Client.APPROVED:
            errors.setdefault("company", []).append("Company must be an approved Client Master record.")

        if self.cessation_date and not self.appointed_date:
            errors.setdefault("cessation_date", []).append("Cessation date cannot be chosen without an appointment date.")
        if self.cessation_date and self.appointed_date and self.cessation_date < self.appointed_date:
            errors.setdefault("cessation_date", []).append("Cessation date cannot be before appointment date.")

        if self.cessation_date and not (self.reason_for_cessation or "").strip():
            errors.setdefault("reason_for_cessation", []).append(
                "Reason for cessation is required when a cessation date is entered."
            )
        if not self.cessation_date and (self.reason_for_cessation or "").strip():
            errors.setdefault("reason_for_cessation", []).append(
                "Reason for cessation should be blank unless a cessation date is entered."
            )

        # At most one active (no cessation) mapping per director+company; reappointment only after cessation.
        if self.director_id and self.company_id:
            active_others = DirectorMapping.objects.filter(
                director_id=self.director_id,
                company_id=self.company_id,
                cessation_date__isnull=True,
            )
            if self.pk:
                active_others = active_others.exclude(pk=self.pk)
            if active_others.exists():
                errors.setdefault("company", []).append(
                    "This director already has an active appointment with this company (no cessation date). "
                    "Record the cessation on that appointment before adding a new one."
                )

        if errors:
            raise ValidationError(errors)

