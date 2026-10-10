from django.contrib import admin

from .models import LogEntry
from .models import Pile
from .models import PlanItem
from .models import PlannerSettings
from .models import PlanPeriod
from .models import Salary


class PlanItemInline(admin.TabularInline):
    model = PlanItem
    extra = 0


@admin.register(PlanPeriod)
class PlanPeriodAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "effective_month",
        "name",
        "cond_pile",
        "cond_op",
        "cond_amount",
    ]
    inlines = [PlanItemInline]


@admin.register(Pile)
class PileAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "kind", "mode", "cap", "order"]


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "user", "type", "from_pile", "to_pile", "amount"]


admin.site.register(PlannerSettings)
admin.site.register(Salary)
