from django import forms

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
            "date": "วันที่",
            "type": "ชนิด",
            "from_pile": "จากกอง",
            "to_pile": "เข้ากอง",
            "amount": "จำนวน (บาท)",
            "note": "โน้ต (ไม่บังคับ)",
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
            msg = "จำนวนต้องมากกว่า 0"
            raise forms.ValidationError(msg)
        return amount

    def clean(self):
        data = super().clean()
        kind, src, dst = data.get("type"), data.get("from_pile"), data.get("to_pile")
        if kind == LogEntry.SPEND and (not src or dst):
            msg = "รายการจ่ายต้องเลือก 'จากกอง' อย่างเดียว"
            raise forms.ValidationError(msg)
        if kind in (LogEntry.TRANSFER, LogEntry.SWEEP) and not (src and dst):
            msg = "การย้ายเงินต้องเลือกทั้ง 'จากกอง' และ 'เข้ากอง'"
            raise forms.ValidationError(msg)
        if kind == LogEntry.ADJUST and bool(src) == bool(dst):
            msg = "การปรับยอดเลือกได้อย่างใดอย่างหนึ่ง (จากกอง หรือ เข้ากอง)"
            raise forms.ValidationError(msg)
        if src and dst and src == dst:
            msg = "กองต้นทางและปลายทางต้องไม่เหมือนกัน"
            raise forms.ValidationError(msg)
        return data

    def save(self, commit=True):  # noqa: FBT002
        self.instance.user = self.user
        return super().save(commit=commit)


class PileForm(forms.ModelForm):
    class Meta:
        model = Pile
        fields = [
            "name", "color", "kind", "mode", "cap", "overflow_to", "target", "order",
        ]  # fmt: skip
        widgets = {
            "name": forms.TextInput(attrs=FIELD),
            "color": forms.TextInput(attrs=FIELD | {"type": "color"}),
            "kind": forms.Select(attrs=FIELD),
            "mode": forms.Select(attrs=FIELD),
            "cap": forms.NumberInput(attrs=FIELD | {"placeholder": "ไม่จำกัด"}),
            "overflow_to": forms.Select(attrs=FIELD),
            "target": forms.NumberInput(attrs=FIELD | {"placeholder": "ไม่มี"}),
            "order": forms.NumberInput(attrs=FIELD),
        }
        labels = {
            "name": "ชื่อกอง",
            "color": "สีประจำกอง",
            "kind": "ชนิด",
            "mode": "โหมดยอดเหลือ",
            "cap": "เพดานทบ (ว่าง = ไม่จำกัด)",
            "overflow_to": "กองที่ล้นไป",
            "target": "เป้าหมาย (กองสะสม)",
            "order": "ลำดับ",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        qs = Pile.objects.filter(user=user)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["overflow_to"].queryset = qs
        self.fields["overflow_to"].empty_label = "—"

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        dup = Pile.objects.filter(user=self.user, name=name)
        if self.instance.pk:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            msg = "ชื่อกองนี้มีอยู่แล้ว"
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
            msg = f"เพิ่มเงินเดือนได้ไม่เกิน {MAX_SALARIES} แถว"
            raise forms.ValidationError(msg)
        return data


class PlanPeriodForm(forms.Form):
    effective_month = MonthField()
    name = forms.CharField(max_length=60, required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_effective_month(self):
        month = self.cleaned_data["effective_month"]
        if PlanPeriod.objects.filter(user=self.user, effective_month=month).exists():
            msg = "มีแผนของเดือนนี้อยู่แล้ว"
            raise forms.ValidationError(msg)
        return month
