from django import forms
from django.utils.translation import gettext_lazy as _

from .models import LogEntry
from .models import Pile
from .models import PlanPeriod
from .models import Salary
from .models import MAX_SALARIES
from .models import month_validator

FIELD = {"class": "field"}


class LogEntryForm(forms.ModelForm):
    class Meta:
        model = LogEntry
        fields = ["date", "type", "from_pile", "to_pile", "amount", "note"]
        widgets = {
            "date": forms.DateInput(attrs=FIELD | {"type": "date"}, format="%Y-%m-%d"),
            "type": forms.Select(attrs=FIELD),
            "from_pile": forms.Select(attrs=FIELD),
            "to_pile": forms.Select(attrs=FIELD),
            "amount": forms.NumberInput(
                attrs=FIELD | {"inputmode": "decimal", "step": "0.01", "placeholder": "0"},
            ),
            "note": forms.TextInput(attrs=FIELD),
        }
        labels = {
            "date": _("Date"),
            "type": _("Type"),
            "from_pile": _("From pile"),
            "to_pile": _("To pile"),
            "amount": _("Amount (THB)"),
            "note": _("Note (optional)"),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        piles = Pile.objects.filter(user=user)
        for name in ("from_pile", "to_pile"):
            self.fields[name].queryset = piles
            self.fields[name].empty_label = "—"

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            msg = _("Amount must be greater than 0")
            raise forms.ValidationError(msg)
        return amount

    def clean(self):
        data = super().clean()
        kind, src, dst = data.get("type"), data.get("from_pile"), data.get("to_pile")
        if kind == LogEntry.SPEND and (not src or dst):
            msg = _("A spend entry needs only a 'From pile'")
            raise forms.ValidationError(msg)
        if kind in (LogEntry.TRANSFER, LogEntry.SWEEP) and not (src and dst):
            msg = _("A transfer needs both a 'From pile' and a 'To pile'")
            raise forms.ValidationError(msg)
        if kind == LogEntry.ADJUST and bool(src) == bool(dst):
            msg = _("An adjustment needs either a 'From pile' or a 'To pile', not both")
            raise forms.ValidationError(msg)
        if src and dst and src == dst:
            msg = _("The source and target piles must differ")
            raise forms.ValidationError(msg)
        return data

    def save(self, commit=True):  # noqa: FBT002
        self.instance.user = self.user
        return super().save(commit=commit)


class PileForm(forms.ModelForm):
    class Meta:
        model = Pile
        fields = [
            "name", "color", "kind", "mode", "cap", "overflow_to",
            "target", "target_percent", "target_months", "order",
        ]  # fmt: skip
        widgets = {
            "name": forms.TextInput(attrs=FIELD),
            "color": forms.TextInput(attrs=FIELD | {"type": "color"}),
            "kind": forms.Select(attrs=FIELD),
            "mode": forms.Select(attrs=FIELD),
            "cap": forms.NumberInput(attrs=FIELD | {"placeholder": _("Unlimited")}),
            "overflow_to": forms.Select(attrs=FIELD),
            "target": forms.NumberInput(attrs=FIELD | {"placeholder": "0"}),
            "target_percent": forms.NumberInput(attrs=FIELD | {"placeholder": "60", "step": "0.01"}),
            "target_months": forms.NumberInput(attrs=FIELD | {"placeholder": "6", "min": "1", "max": "120"}),
            "order": forms.NumberInput(attrs=FIELD),
        }
        labels = {
            "name": _("Pile name"),
            "color": _("Pile color"),
            "kind": _("Type"),
            "mode": _("Leftover mode"),
            "cap": _("Rollover cap (empty = unlimited)"),
            "overflow_to": _("Overflow pile"),
            "target": _("Target amount (THB)"),
            "target_percent": _("Share of salary (%)"),
            "target_months": _("Months of salary"),
            "order": _("Order"),
        }

    TARGET_MODES = [
        ("none", _("No target")),
        ("fixed", _("A fixed amount")),
        ("salary", _("A share of my salary x months")),
    ]
    target_mode = forms.ChoiceField(
        choices=TARGET_MODES,
        label=_("Target"),
        widget=forms.Select(attrs=FIELD),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        qs = Pile.objects.filter(user=user)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["overflow_to"].queryset = qs
        self.fields["overflow_to"].empty_label = "—"
        for name in ("target", "target_percent", "target_months"):
            self.fields[name].required = False
        pile = self.instance
        self.fields["target_mode"].initial = (
            "salary" if pile.has_salary_target else "fixed" if pile.target is not None else "none"
        )
        self.order_fields([
            "name", "color", "kind", "mode", "cap", "overflow_to",
            "target_mode", "target", "target_percent", "target_months", "order",
        ])  # fmt: skip

    def clean(self):
        data = super().clean()
        mode = data.get("target_mode")
        if mode == "fixed":
            if data.get("target") is None:
                self.add_error("target", _("Enter the target amount"))
            data["target_percent"] = data["target_months"] = None
        elif mode == "salary":
            if data.get("target_percent") is None:
                self.add_error("target_percent", _("Enter a percentage of your salary"))
            if not data.get("target_months"):
                self.add_error("target_months", _("Enter the number of months"))
            data["target"] = None
        else:
            data["target"] = data["target_percent"] = data["target_months"] = None
        return data

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        dup = Pile.objects.filter(user=self.user, name=name)
        if self.instance.pk:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            msg = _("A pile with this name already exists")
            raise forms.ValidationError(msg)
        return name

    def save(self, commit=True):  # noqa: FBT002
        self.instance.user = self.user
        return super().save(commit=commit)


class MonthField(forms.CharField):
    default_validators = [month_validator]


class SalaryForm(forms.Form):
    effective_month = MonthField()
    amount = forms.DecimalField(min_value=0, max_digits=14, decimal_places=2)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        data = super().clean()
        if Salary.objects.filter(user=self.user).count() >= MAX_SALARIES:
            msg = _("You can add at most %(max)s salaries") % {"max": MAX_SALARIES}
            raise forms.ValidationError(msg)
        return data


class PlanPeriodForm(forms.Form):
    effective_month = MonthField()
    name = forms.CharField(max_length=60, required=False)


class PlanConditionForm(forms.Form):
    """Optional "only use this plan while <pile> <has at least|is below> <amount>"."""

    condition_mode = forms.ChoiceField(choices=[("", ""), ("on", "on")], required=False)
    condition_pile = forms.ModelChoiceField(queryset=Pile.objects.none(), required=False)
    condition_op = forms.ChoiceField(choices=PlanPeriod.OP_CHOICES, required=False)
    condition_use_target = forms.BooleanField(required=False)
    condition_amount = forms.DecimalField(
        min_value=0,
        max_digits=14,
        decimal_places=2,
        required=False,
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["condition_pile"].queryset = Pile.objects.filter(user=user)

    def clean(self):
        data = super().clean()
        if data.get("condition_mode") != "on":
            return {
                "cond_pile": None,
                "cond_op": "",
                "cond_amount": None,
                "cond_use_target": False,
            }
        pile = data.get("condition_pile")
        use_target = bool(data.get("condition_use_target"))
        amount = data.get("condition_amount")
        if use_target:
            if pile is not None and not pile.has_target:
                msg = _("This pile has no target. Set one on the Piles tab or enter an amount.")
                raise forms.ValidationError(msg)
            amount = pile.target if pile else None
        if not (pile and data.get("condition_op") and (use_target or amount is not None)):
            msg = _("Choose a pile, a comparison and an amount for the condition")
            raise forms.ValidationError(msg)
        return {
            "cond_pile": pile,
            "cond_op": data["condition_op"],
            "cond_amount": amount,
            "cond_use_target": use_target,
        }
