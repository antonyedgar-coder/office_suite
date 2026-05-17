import json



from django import forms

from django.contrib.auth import get_user_model

from django.core.exceptions import ValidationError as DjangoValidationError



from core.branch_access import approved_clients_for_user, client_allowed_for_user

from masters.models import Client

from mis.forms import ClientNamePanChoiceField



from .models import Task, TaskGroup, TaskMaster

from .period_keys import (

    HALF_CHOICES,

    MONTH_CHOICES,

    PERIOD_TYPE_CHOICES,

    QUARTER_CHOICES,

    build_period_key,
    current_fy_start,
    task_fy_choices,
)

from .recurrence_config import validate_recurrence_config

from .user_labels import staff_users_queryset, user_display_label



User = get_user_model()





def _fy_dropdown_choices():

    return task_fy_choices()





class TaskGroupForm(forms.ModelForm):

    class Meta:

        model = TaskGroup

        fields = ["name", "sort_order", "is_active"]

        widgets = {

            "name": forms.TextInput(attrs={"class": "form-control"}),

            "sort_order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),

            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),

        }





class TaskMasterForm(forms.ModelForm):

    recurrence_config_json = forms.CharField(

        required=False,

        widget=forms.HiddenInput(),

    )

    checklist_json = forms.CharField(

        required=False,

        widget=forms.HiddenInput(),

    )



    class Meta:

        model = TaskMaster

        fields = [

            "task_group",

            "name",

            "description",

            "default_priority",

            "is_active",

            "is_recurring",

            "frequency",

            "default_is_billable",

            "default_fees_amount",

            "default_currency",

            "default_verifier",

        ]

        widgets = {

            "task_group": forms.Select(attrs={"class": "form-select"}),

            "name": forms.TextInput(attrs={"class": "form-control"}),

            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),

            "default_priority": forms.Select(attrs={"class": "form-select"}),

            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),

            "is_recurring": forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_is_recurring"}),

            "frequency": forms.Select(attrs={"class": "form-select", "id": "id_frequency"}),

            "default_is_billable": forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_default_is_billable"}),

            "default_fees_amount": forms.NumberInput(attrs={"class": "form-control", "id": "id_default_fees_amount", "step": "0.01", "min": "0"}),

            "default_currency": forms.TextInput(attrs={"class": "form-control", "maxlength": 8}),

            "default_verifier": forms.Select(attrs={"class": "form-select"}),

        }



    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields["task_group"].queryset = TaskGroup.objects.filter(is_active=True).order_by(

            "sort_order", "name"

        )

        self.fields["default_verifier"].queryset = staff_users_queryset()

        self.fields["default_verifier"].required = False

        if self.instance and self.instance.pk and self.instance.recurrence_config:

            self.fields["recurrence_config_json"].initial = json.dumps(self.instance.recurrence_config)

        if self.instance and self.instance.pk:

            from .checklist import master_checklist_labels

            self.fields["checklist_json"].initial = json.dumps(master_checklist_labels(self.instance))



    def clean(self):

        cleaned = super().clean()

        is_recurring = cleaned.get("is_recurring")

        frequency = cleaned.get("frequency") or ""

        raw = cleaned.get("recurrence_config_json") or "{}"

        try:

            cfg = json.loads(raw) if raw else {}

        except json.JSONDecodeError as exc:

            raise forms.ValidationError(

                {"recurrence_config_json": "Invalid recurrence configuration JSON."}

            ) from exc

        if is_recurring:

            try:

                validate_recurrence_config(frequency, cfg)

            except DjangoValidationError as exc:

                raise self._recurrence_validation_error(exc) from exc

            self.instance.recurrence_config = cfg

        else:

            cleaned["frequency"] = ""

            self.instance.recurrence_config = {}

            self.instance.frequency = ""

        raw_checklist = cleaned.get("checklist_json") or "[]"

        try:

            checklist_data = json.loads(raw_checklist) if raw_checklist else []

        except json.JSONDecodeError as exc:

            raise forms.ValidationError({"checklist_json": "Invalid checklist data."}) from exc

        if isinstance(checklist_data, list):

            cleaned["checklist_items"] = [

                str(item).strip() for item in checklist_data if str(item).strip()

            ]

        else:

            cleaned["checklist_items"] = []

        if cleaned.get("default_is_billable") and cleaned.get("default_fees_amount") is None:

            self.add_error("default_fees_amount", "Enter default fees when billable is enabled.")

        if not cleaned.get("default_is_billable"):

            cleaned["default_fees_amount"] = None

        return cleaned



    def _recurrence_validation_error(self, exc: DjangoValidationError) -> forms.ValidationError:

        if hasattr(exc, "message_dict"):

            messages = []

            for errors in exc.message_dict.values():

                messages.extend(errors)

            return forms.ValidationError(

                {"recurrence_config_json": messages or ["Invalid recurrence configuration."]}

            )

        return forms.ValidationError(

            {"recurrence_config_json": exc.messages or ["Invalid recurrence configuration."]}

        )



    def save(self, commit=True):

        instance = super().save(commit=commit)

        if commit:

            from .checklist import save_master_checklist

            save_master_checklist(instance, self.cleaned_data.get("checklist_items", []))

        return instance





class StaffUserChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj: User) -> str:

        return user_display_label(obj)





class TaskCreateForm(forms.Form):

    task_master = forms.ModelChoiceField(

        queryset=TaskMaster.objects.none(),

        widget=forms.Select(attrs={"class": "form-select"}),

    )

    client = ClientNamePanChoiceField(

        queryset=Client.objects.none(),

        widget=forms.HiddenInput(attrs={"data-task-client-hidden": "1"}),

    )

    client_search = forms.CharField(

        label="Client",

        required=False,

        widget=forms.TextInput(

            attrs={

                "class": "form-control",

                "id": "taskClientSearch",

                "placeholder": "Type client name or PAN (min. 2 characters)…",

                "autocomplete": "off",

            }

        ),

    )

    assignee_ids = forms.CharField(

        required=False,

        widget=forms.HiddenInput(attrs={"id": "taskAssigneeIdsHidden"}),

    )

    assignee_picker = forms.CharField(

        label="Users",

        required=False,

        widget=forms.TextInput(

            attrs={

                "class": "form-control",

                "id": "taskAssigneeSearch",

                "placeholder": "Type name or email to add users…",

                "autocomplete": "off",

            }

        ),

    )

    verifier = StaffUserChoiceField(

        queryset=User.objects.none(),

        widget=forms.Select(attrs={"class": "form-select", "id": "id_verifier"}),

        empty_label="Select verifier…",

    )

    period_type = forms.ChoiceField(

        label="Filing period",

        choices=PERIOD_TYPE_CHOICES,

        widget=forms.Select(attrs={"class": "form-select", "id": "id_period_type"}),

    )

    period_month = forms.ChoiceField(

        label="Month",

        choices=[("", "Select month")] + list(MONTH_CHOICES),

        required=False,

        widget=forms.Select(attrs={"class": "form-select", "data-period-field": "monthly"}),

    )

    period_year = forms.ChoiceField(

        label="Financial year",

        choices=[("", "Select FY")],

        required=False,

        widget=forms.Select(attrs={"class": "form-select", "data-period-field": "monthly"}),

    )

    period_quarter = forms.ChoiceField(

        label="Quarter",

        choices=[("", "Select quarter")] + list(QUARTER_CHOICES),

        required=False,

        widget=forms.Select(attrs={"class": "form-select", "data-period-field": "quarterly"}),

    )

    period_fy = forms.ChoiceField(

        label="Financial year",

        choices=[("", "Select FY")],

        required=False,

        widget=forms.Select(attrs={"class": "form-select", "data-period-field": "quarterly half_yearly yearly"}),

    )

    period_half = forms.ChoiceField(

        label="Half year",

        choices=[("", "Select half")] + list(HALF_CHOICES),

        required=False,

        widget=forms.Select(attrs={"class": "form-select", "data-period-field": "half_yearly"}),

    )

    period_year_from = forms.ChoiceField(

        label="From FY",

        choices=[("", "From FY")],

        required=False,

        widget=forms.Select(attrs={"class": "form-select", "data-period-field": "every_3_years every_5_years"}),

    )

    period_year_to = forms.ChoiceField(

        label="To FY",

        choices=[("", "To FY")],

        required=False,

        widget=forms.Select(attrs={"class": "form-select", "data-period-field": "every_3_years every_5_years"}),

    )

    due_date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))

    priority = forms.ChoiceField(

        choices=TaskMaster.PRIORITY_CHOICES,

        widget=forms.Select(attrs={"class": "form-select"}),

    )

    is_billable = forms.BooleanField(

        required=False,

        initial=False,

        label="Billable",

        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_is_billable"}),

    )

    fees_amount = forms.DecimalField(

        required=False,

        min_value=0,

        max_digits=12,

        decimal_places=2,

        label="Fees amount",

        widget=forms.NumberInput(attrs={"class": "form-control", "id": "id_fees_amount", "step": "0.01", "min": "0"}),

    )



    def __init__(self, *args, user=None, **kwargs):

        self._task_user = user

        super().__init__(*args, **kwargs)

        staff_qs = staff_users_queryset()

        fy_choices = [("", "Select FY")] + _fy_dropdown_choices()

        self.fields["period_year"].choices = fy_choices

        self.fields["period_fy"].choices = fy_choices

        self.fields["period_year_from"].choices = [("", "From FY")] + _fy_dropdown_choices()

        self.fields["period_year_to"].choices = [("", "To FY")] + _fy_dropdown_choices()

        cur_fy = str(current_fy_start())

        if not self.is_bound:

            self.fields["period_year"].initial = cur_fy

            self.fields["period_fy"].initial = cur_fy

            self.fields["period_year_from"].initial = cur_fy

            self.fields["period_year_to"].initial = str(current_fy_start() + 2)



        if user is not None:

            self.fields["client"].queryset = approved_clients_for_user(user)

        self.fields["task_master"].queryset = (

            TaskMaster.objects.filter(is_active=True)

            .select_related("task_group")

            .order_by("task_group__sort_order", "name")

        )

        self.fields["verifier"].queryset = staff_qs

        self._staff_qs = staff_qs



    def clean(self):

        cleaned = super().clean()

        if not cleaned.get("client"):

            self.add_error("client_search", "Please select a client from the suggestions.")

        client = cleaned.get("client")

        if client and self._task_user and not client_allowed_for_user(self._task_user, client):

            self.add_error("client_search", "This client is not in your branch.")



        raw_ids = (cleaned.get("assignee_ids") or "").strip()

        ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]

        assignees = list(self._staff_qs.filter(pk__in=ids))

        if not assignees or len(assignees) != len(set(ids)):

            self.add_error("assignee_picker", "Add at least one valid user from the suggestions.")

        cleaned["assignees"] = assignees



        period_type = cleaned.get("period_type")

        try:

            if period_type == "monthly":
                fy_for_period = _int_or_none(cleaned.get("period_year"))
            elif period_type in ("quarterly", "half_yearly", "yearly"):
                fy_for_period = _int_or_none(cleaned.get("period_fy"))
            else:
                fy_for_period = None

            cleaned["period_key"] = build_period_key(

                period_type,

                month=_int_or_none(cleaned.get("period_month")),

                quarter=cleaned.get("period_quarter") or None,

                fy_start=fy_for_period,

                half=cleaned.get("period_half") or None,

                year_from=_int_or_none(cleaned.get("period_year_from")),

                year_to=_int_or_none(cleaned.get("period_year_to")),

            )

        except DjangoValidationError as exc:

            if hasattr(exc, "message_dict"):

                for field, errs in exc.message_dict.items():

                    self.add_error(field if field in self.fields else "period_type", errs)

            else:

                self.add_error("period_type", exc.messages)



        master = cleaned.get("task_master")

        if client and master and cleaned.get("period_key"):

            if Task.objects.filter(

                client=client,

                task_master=master,

                period_key=cleaned["period_key"],

            ).exists():

                raise forms.ValidationError(

                    "A task for this client, task master, and filing period already exists."

                )

        if cleaned.get("is_billable") and cleaned.get("fees_amount") is None:

            self.add_error("fees_amount", "Enter the fees amount for billable tasks.")

        if not cleaned.get("is_billable"):

            cleaned["fees_amount"] = None

        return cleaned





def _int_or_none(value) -> int | None:

    if value in (None, ""):

        return None

    return int(value)





class TaskRemarkForm(forms.Form):

    message = forms.CharField(

        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),

        required=True,

    )





class TaskVerifyForm(forms.Form):

    message = forms.CharField(

        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),

        required=False,

    )


