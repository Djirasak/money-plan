from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "to", "template", "status", "attempts", "sent_at"]
    list_filter = ["status", "template"]
    search_fields = ["to", "message_id", "dedupe_key", "subject"]
    date_hierarchy = "created_at"
    exclude = ["body_html"]
    readonly_fields = ["preview", "body_text"]

    @admin.display(description=_("Preview"))
    def preview(self, obj):
        # srcdoc + an empty sandbox: the stored mail renders, but its markup can run nothing
        return format_html(
            '<iframe sandbox srcdoc="{}" style="width:100%;max-width:640px;height:480px;border:1px solid #ccc;background:#fff"></iframe>',
            obj.body_html,
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
